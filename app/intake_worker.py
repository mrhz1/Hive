"""Redacting a swept batch -- built for millions of files.

Four things make it scale, each measured or forced by Hive:

- **Chunks, not files.** The pipeline is handed many files per run, so
  PaddleOCR and the NER model load once per chunk. Measured on DICOMs:
  1.07 s each in chunks of 40, against ~7.5 s each one at a time.
- **Shards.** Rows are divided by the first two hex characters of their id;
  a process owns a set of shards and claims only inside it, so processes on
  different machines can never take the same file. Within a process, one
  thread claims and N run -- Hive has no atomic claim, so N threads asking
  for "the next queued row" would all be handed the same one.
- **A journal.** Each outcome is appended to a local file the moment it is
  known, and published to Hive in one statement per chunk. A worker killed
  between the two loses nothing: the next start publishes what was
  finished and requeues only what was not.
- **A heartbeat.** Each process writes what it is doing every few seconds,
  which is what the progress page reads and how a stopped worker is
  noticed.

Each file comes out in the mirror, beside where it went in:

    incoming_data/A/B/C/AA1234/image.dcm
    incoming_data/de_identified/A/B/C/AA1234/AA1234_<date>_<serial>.dcm

Nothing here touches an application or a patient record. A patient does not
exist yet -- the code on the document is all there is -- so this is a pure
file-in, file-out job whose only bookkeeping is the intake row.
"""

import json
import os
import queue
import shutil
import socket
import threading
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from app import deid, intake
from app.crud import intake_files as crud
from app.db import hive_cursor
from app.embed import embed_metadata, generated_facts
from app.logging_setup import get_logger
from app.schemas import IntakeFileUpdate  # noqa: F401 -- re-exported for callers

log = get_logger(__name__)


def workers() -> int:
    """How many files are redacted at once.

    One by default: OCR and the NER models are the memory cost, and a
    worker that is killed for running out of memory (exit -9) produces
    nothing. Raise it against measured peak usage, not optimism --
    `N = min(cores / cores_per_worker, RAM / RAM_per_worker)`.
    """
    return max(1, int(os.environ.get("DEID_WORKERS", "1")))


def worker_cpu_threads() -> Optional[str]:
    """Cores each worker may use, injected per subprocess.

    OCR_CPU_THREADS defaults to 8 inside the pipeline, which is the right
    number for one worker and four times the machine for four of them.
    Unset here, nothing is injected and the pipeline's own default stands.
    """
    return os.environ.get("DEID_WORKER_CPU_THREADS")


def worker_memory_gb() -> Optional[float]:
    """Advisory only.

    A process cannot cap its own memory; that is the container's job (the
    CML Job's setting, or the host's). This is used to refuse to start more
    workers than the machine can hold, which is the part that is actually
    enforceable here.
    """
    raw = os.environ.get("DEID_WORKER_MEMORY_GB")
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


def _subprocess_env() -> Optional[dict]:
    threads = worker_cpu_threads()
    if not threads:
        return None
    # OMP/MKL as well as the pipeline's own knob: the NLP stage's libraries
    # help themselves to every core otherwise, which undoes the budget.
    return {
        "OCR_CPU_THREADS": threads,
        "OMP_NUM_THREADS": threads,
        "MKL_NUM_THREADS": threads,
    }


def _available_memory_gb() -> Optional[float]:
    """What the machine says it has free, where it says anything."""
    try:
        pages = os.sysconf("SC_AVPHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
    except (ValueError, OSError, AttributeError):  # pragma: no cover
        return None
    return (pages * page_size) / (1024**3)


def safe_worker_count() -> int:
    """`DEID_WORKERS`, capped by what the machine can actually hold.

    Starting eight workers on a box with room for two does not run eight
    times faster; it gets some of them killed mid-document, and a killed
    run leaves a file marked failed for a reason that has nothing to do
    with the file.
    """
    wanted = workers()
    per_worker = worker_memory_gb()
    if not per_worker:
        return wanted

    available = _available_memory_gb()
    if not available:
        return wanted

    fits = max(1, int(available // per_worker))
    if fits < wanted:
        log.warning(
            "intake_workers_capped",
            wanted=wanted,
            running=fits,
            available_gb=round(available, 1),
            per_worker_gb=per_worker,
        )
    return min(wanted, fits)


# --- configuration -------------------------------------------------------

PREFIXES = [f"{n:02x}" for n in range(256)]


def chunk_dicom() -> int:
    """DICOMs per pipeline run. Memory stayed flat at ~0.84 GB from 1 to 40."""
    return max(1, int(os.environ.get("DEID_CHUNK_DICOM", "40")))


def chunk_documents() -> int:
    """PDF/Word files per pipeline run.

    Small, and each file OCR'd on its own inside the run
    (DEID_OCR_BATCH_SIZE=1): a multi-page scan is rasterised page by page,
    and a process handed several at once is the one that gets killed.
    """
    return max(1, int(os.environ.get("DEID_CHUNK_DOCUMENTS", "4")))


def shard_prefixes(shards: Optional[Iterable[int]] = None, of: int = 1) -> List[str]:
    """The id prefixes shard set `shards` (out of `of`) owns.

    Worker k of N owns the prefixes whose value mod N is k. Default: all of
    them -- one process doing everything.
    """
    of = max(1, int(of))
    wanted = set(range(of)) if shards is None else {int(k) % of for k in shards}
    return [p for p in PREFIXES if int(p, 16) % of in wanted]


def worker_name() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


def _state_dir(root: Path) -> Path:
    return root / ".intake"


# --- the journal ---------------------------------------------------------


class Journal:
    """Outcomes written locally before Hive knows them.

    Append-only JSON lines, fsync'd, one file per worker thread. Publishing
    a chunk's outcomes to Hive and then clearing the file is the only
    two-step moment, and it is safe both ways round: a crash before the
    publish leaves the outcomes here to be published on the next start; a
    crash after it but before the clear publishes them twice, which changes
    nothing.
    """

    def __init__(self, root: Path, name: str):
        self.path = _state_dir(root) / "journal" / f"{name}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def append(self, result: dict) -> None:
        line = json.dumps(result, separators=(",", ":")) + "\n"
        with self._lock, open(self.path, "a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())

    def clear(self) -> None:
        with self._lock:
            self.path.unlink(missing_ok=True)

    @staticmethod
    def read(path: Path) -> List[dict]:
        out = []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return out
        for line in lines:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                # A line half-written when the process died. Its file is
                # still `processing` in Hive and will be redone.
                continue
        return out


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _journal_is_orphaned(path: Path, root: Path) -> bool:
    """Whether a journal's writer is gone, so its outcomes are ours to publish.

    Named `<host>-<pid>-t<n>`. On this host, the pid tells us; on another
    host, its heartbeat does -- stale for HEARTBEAT_STALE_SECONDS means dead.
    """
    host, _, rest = path.stem.rpartition("-t")[0].rpartition("-")
    try:
        pid = int(rest)
    except ValueError:
        return False
    if host == socket.gethostname():
        return not _pid_alive(pid)
    beat = _state_dir(root) / "workers" / f"{host}-{pid}.json"
    try:
        return time.time() - beat.stat().st_mtime > HEARTBEAT_STALE_SECONDS
    except OSError:
        return True


def replay_journals(cursor, root: Path) -> int:
    """Publish outcomes that dead workers finished but never recorded.

    Work already done is not done again: a chunk that finished its OCR and
    was killed before writing to Hive keeps its results.
    """
    directory = _state_dir(root) / "journal"
    if not directory.is_dir():
        return 0
    published = 0
    for path in sorted(directory.glob("*.jsonl")):
        if not _journal_is_orphaned(path, root):
            continue
        results = Journal.read(path)
        if results:
            _publish(cursor, results)
            published += len(results)
        path.unlink(missing_ok=True)
    if published:
        log.warning("intake_journal_replayed", results=published)
    return published


def _publish(cursor, results: List[dict], attempts: int = 4) -> None:
    """One statement for a chunk's outcomes, retried if Hive refuses.

    Hive can abort a write that races another on the same table. The
    outcomes are safe in the journal meanwhile, and applying them twice is
    harmless, so retrying is always right.
    """
    for attempt in range(1, attempts + 1):
        try:
            crud.apply_results(cursor, results)
            return
        except Exception as exc:
            if attempt == attempts:
                raise
            wait = 2**attempt
            log.warning(
                "intake_publish_retry", attempt=attempt, wait_seconds=wait, error=str(exc)
            )
            time.sleep(wait)


# --- the heartbeat ------------------------------------------------------

HEARTBEAT_STALE_SECONDS = float(os.environ.get("INTAKE_HEARTBEAT_STALE_SECONDS", "300"))


class Heartbeat:
    """What this process is doing, written every few seconds.

    The progress page reads these files: which workers are alive, what each
    is on, how fast each is going. A worker whose file stops changing has
    stopped -- that is the stalled warning.
    """

    def __init__(self, root: Path, shards: List[int], of: int, pool: int):
        # Named for the role -- this machine, these shards -- not the process.
        # A scheduled Job starts a new process every minute; named per pid,
        # that is 1,400 files a day and a speed history that resets each run.
        role = f"{socket.gethostname()}-" + (
            "all" if of <= 1 else f"{of}-" + "_".join(str(k) for k in shards)
        )
        self.path = _state_dir(root) / "workers" / f"{role}.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        previous = {}
        try:
            previous = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            pass
        self.state = {
            "name": role,
            "host": socket.gethostname(),
            "pid": os.getpid(),
            "shards": shards,
            "of": of,
            "workers": pool,
            "started_at": time.time(),
            "last_seen": time.time(),
            "status": "working",
            "current": [],
            # Totals and the last hour's per-minute completions carry over
            # from the previous run in this role, so the rate survives it.
            "done": int(previous.get("done", 0)),
            "failed": int(previous.get("failed", 0)),
            "per_minute": {
                k: v for k, v in (previous.get("per_minute") or {}).items()
                if int(k) >= time.time() - 3600
            },
        }
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._beat, name="intake-heartbeat", daemon=True)

    def start(self) -> "Heartbeat":
        self.write()
        self._thread.start()
        return self

    def _beat(self) -> None:
        while not self._stop.wait(5):
            self.write()

    def working_on(self, names: List[str]) -> None:
        with self._lock:
            self.state["current"] = names[:10]

    def finished(self, done: int, failed: int) -> None:
        minute = str(int(time.time() // 60 * 60))
        with self._lock:
            self.state["done"] += done
            self.state["failed"] += failed
            per = self.state["per_minute"]
            per[minute] = per.get(minute, 0) + done + failed
            cutoff = time.time() - 3600
            for key in [k for k in per if int(k) < cutoff]:
                del per[key]

    def write(self) -> None:
        with self._lock:
            self.state["last_seen"] = time.time()
            data = json.dumps(self.state)
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text(data)
            tmp.replace(self.path)
        except OSError as exc:  # pragma: no cover - progress is best effort
            log.warning("intake_heartbeat_failed", error=str(exc))

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            self.state["status"] = "idle"
            self.state["current"] = []
        self.write()


def read_heartbeats(root: Path) -> List[dict]:
    beats = []
    directory = _state_dir(root) / "workers"
    if not directory.is_dir():
        return beats
    for path in sorted(directory.glob("*.json")):
        try:
            beats.append(json.loads(path.read_text()))
        except (OSError, json.JSONDecodeError):
            continue
    return beats


# --- one chunk -----------------------------------------------------------


class RedactionError(Exception):
    pass


def _root_of(record) -> Path:
    """The intake root this file was found under.

    Derived from the two paths already on the row rather than looked up:
    a batch can be swept from somewhere other than the configured root, and
    its mirror belongs beside the originals, not beside the default.
    """
    source = Path(record.source_path)
    depth = len(Path(record.relative_path).parts)
    try:
        return source.parents[depth - 1]
    except IndexError:  # pragma: no cover - only if the row is inconsistent
        return intake.intake_root()


def _settled_enough(record) -> bool:
    source = Path(record.source_path)
    if intake.batch_is_marked_done(source.parent):
        return True
    return intake.is_settled(source)


def _is_dicom(record) -> bool:
    return (record.file_extension or "").lower() in ("dcm", "dicom")


def _units(records: list, workers: int = 1) -> List[Tuple[list, int]]:
    """Split claimed files into pipeline runs: (records, OCR batch size).

    DICOMs together, OCR'd in one batch; documents a few per run, OCR'd one
    at a time -- see chunk_documents.

    Spread across `workers` as well: runs are made small enough that every
    worker gets one. Packing three PDFs into one run left one worker doing
    all three in turn while the rest sat idle. With a big queue the runs
    stay full-size (DEID_CHUNK_*), so the models still load rarely.
    """
    workers = max(1, workers)
    dicoms = [r for r in records if _is_dicom(r)]
    documents = [r for r in records if not _is_dicom(r)]

    def size(count: int, cap: int) -> int:
        return max(1, min(cap, -(-count // workers)))

    units: List[Tuple[list, int]] = []
    step = size(len(dicoms), chunk_dicom())
    for start in range(0, len(dicoms), step):
        part = dicoms[start : start + step]
        units.append((part, len(part)))
    step = size(len(documents), chunk_documents())
    for start in range(0, len(documents), step):
        units.append((documents[start : start + step], 1))
    return units


def redact_unit(records: list, ocr_batch: int, workdir: Path) -> List[dict]:
    """One pipeline run's worth. See redact_records for the retry rule."""
    results = _run(records, ocr_batch, workdir / "run")
    if len(records) > 1:
        retry = [r for r in records if isinstance(results.get(r.id), Exception)]
        for record in retry:
            results.update(_run([record], 1, workdir / "one"))
    outcomes = [_settle(record, results.get(record.id)) for record in records]
    shutil.rmtree(workdir, ignore_errors=True)
    return outcomes


def _run(records: list, ocr_batch: int, workdir: Path) -> Dict[str, object]:
    """One pipeline run over `records`. Returns {id: produced | DeidError}.

    Each file goes in as `<id>.<type>`, a link to the original:
    - the pipeline writes a whole run into one folder, so two `image.dcm`
      from different folders would collide under their own names;
    - its outputs come back named by id, so matching them up is exact;
    - the pipeline picks the reader by extension, and a PACS export called
      `IM000001` has none -- the link carries the type the sweep found in
      the bytes.
    """
    inputs = workdir / "in"
    outputs = workdir / "out"
    shutil.rmtree(workdir, ignore_errors=True)
    inputs.mkdir(parents=True)

    links: Dict[str, str] = {}
    results: Dict[str, object] = {}
    for record in records:
        source = Path(record.source_path)
        if not source.is_file():
            results[record.id] = deid.DeidError(
                "the file is no longer at the path it was found at"
            )
            continue
        link = inputs / f"{record.id}.{(record.file_extension or 'bin').lower()}"
        link.symlink_to(source)
        links[str(link)] = record.id

    if links:
        env = dict(_subprocess_env() or {})
        env["DEID_OCR_BATCH_SIZE"] = str(ocr_batch)
        outcome = deid.run_pipeline_many([Path(l) for l in links], outputs, env=env)
        for link, record_id in links.items():
            results[record_id] = outcome.get(link, deid.DeidError("no result"))
    return results


def _file_outputs(produced: Path, record, code: str) -> Path:
    """Move a run's outputs into the mirror, renamed `<CODE>_<date>_<serial>`.

    The copy, its extracted text and its report share one stem and move
    together, because they are found as a set.
    """
    target_dir = intake.mirrored_dir(record.relative_path, _root_of(record))
    target_dir.mkdir(parents=True, exist_ok=True)
    stem = deid._free_output_stem(target_dir, code, produced.suffix)

    old_stem = produced.stem
    for path in sorted(produced.parent.iterdir()):
        if path.is_file() and path.name.startswith(old_stem):
            shutil.move(str(path), str(target_dir / (stem + path.name[len(old_stem):])))
    return target_dir / f"{stem}{produced.suffix}"


def redact_records(records: list, workdir: Path) -> List[dict]:
    """Redact files. Returns one outcome per record, never raises.

    If a run of several files fails any of them, those are run again one at
    a time: a run killed outright -- one oversized scan running the process
    out of memory -- fails every file in it, and nineteen good files must not
    be marked failed for the twentieth.
    """
    outcomes: List[dict] = []
    for unit, ocr_batch in _units(records):
        outcomes.extend(redact_unit(unit, ocr_batch, workdir))
    return outcomes


def _settle(record, result) -> dict:
    code = record.patient_code or ""
    method = None
    if isinstance(result, deid.Produced):
        result, method = result.path, result.method
    if not isinstance(result, Path):
        detail = str(result) if result is not None else "no result"
        log.error("intake_file_failed", file_id=record.id, error=detail)
        return {"id": record.id, "status": "failed", "output_path": None,
                "output_name": None, "detail": detail}
    try:
        final = _file_outputs(result, record, code)
        embed_metadata(
            final,
            final.suffix.lstrip(".").lower(),
            generated_facts(
                patient_id=code,
                output_name=final.name,
                output_type=final.suffix.lstrip(".").lower(),
                by="intake sweep",
                source_name=record.file_name,
            ),
        )
    except Exception as exc:  # pragma: no cover - a worker must not die
        log.exception("intake_file_crashed", file_id=record.id, error=str(exc))
        return {"id": record.id, "status": "failed", "output_path": None,
                "output_name": None, "detail": f"unexpected: {exc}"}
    # For a DICOM, which way it went -- pixels redacted, or tags only because
    # the image held no text (or nothing identifying). Kept for audit.
    return {"id": record.id, "status": "done", "output_path": str(final),
            "output_name": final.name, "detail": method}


def redact_one(record) -> bool:
    """Redact one claimed file and record the outcome. For tools and tests."""
    root = _root_of(record)
    outcome = redact_records([record], _state_dir(root) / "work" / f"{worker_name()}-one")[0]
    with hive_cursor() as cursor:
        _publish(cursor, [outcome])
    return outcome["status"] == "done"


# --- claiming -----------------------------------------------------------


def claim_chunk(cursor, prefixes: List[str], size: int, check_settled: bool = True) -> list:
    """Take up to `size` queued files from a shard, marking them processing.

    Two statements for the whole chunk. Files still being copied in are left
    queued when `check_settled` -- intake_run turns that off once it has
    established the push has finished, having removed the marker that would
    otherwise vouch for them.
    """
    candidates = crud.list_queued(cursor, prefixes, size)
    if check_settled:
        candidates = [r for r in candidates if _settled_enough(r)]
    if candidates:
        crud.set_status_many(cursor, [r.id for r in candidates], "processing")
    return candidates


def recover(cursor, root: Path, prefixes: List[str]) -> int:
    """Before working a shard: publish what dead workers finished, then put
    back in the queue whatever they left half-done.

    Only the shard's own rows are touched -- another process on another
    machine may be working the rest.
    """
    replay_journals(cursor, root)
    requeued = crud.requeue_processing(cursor, prefixes)
    if requeued:
        log.warning("intake_rows_recovered", requeued=requeued)
    return requeued


def drain(
    limit: Optional[int] = None,
    pool_size: Optional[int] = None,
    check_settled: bool = True,
    shards: Optional[Iterable[int]] = None,
    of: int = 1,
    root: Optional[Path] = None,
) -> dict:
    """Redact everything queued in this process's shards.

    One thread claims chunks; `pool_size` threads each run a chunk through
    the pipeline, journal every outcome, and publish the chunk to Hive in
    one statement. Returns a tally rather than raising: one bad document out
    of a million is a row marked failed, not a reason to stop.
    """
    root = root or intake.intake_root()
    size = pool_size or safe_worker_count()
    prefixes = shard_prefixes(shards, of)
    shard_list = sorted({int(p, 16) % max(1, of) for p in prefixes})

    tally = {"done": 0, "failed": 0}
    counted = threading.Lock()
    work: "queue.Queue" = queue.Queue(maxsize=size)
    beat = Heartbeat(root, shard_list, of, size).start()

    def run(index: int):
        journal = Journal(root, f"{worker_name()}-t{index}")
        workdir = _state_dir(root) / "work" / f"{worker_name()}-t{index}"
        while True:
            item = work.get()
            try:
                if item is None:
                    return
                records, ocr_batch = item
                beat.working_on([r.file_name for r in records])
                outcomes = redact_unit(records, ocr_batch, workdir)
                for outcome in outcomes:
                    journal.append(outcome)
                with hive_cursor() as cursor:
                    _publish(cursor, outcomes)
                journal.clear()
                done = sum(1 for o in outcomes if o["status"] == "done")
                beat.finished(done, len(outcomes) - done)
                with counted:
                    tally["done"] += done
                    tally["failed"] += len(outcomes) - done
            except Exception as exc:  # pragma: no cover - the thread must not die
                # The journal keeps what was finished; the rest stays
                # `processing` and is recovered on the next start.
                log.exception("intake_chunk_error", error=str(exc))
            finally:
                work.task_done()

    threads = [
        threading.Thread(target=run, args=(n,), name=f"intake-worker-{n}", daemon=True)
        for n in range(size)
    ]
    for thread in threads:
        thread.start()

    log.debug("intake_drain_started", workers=size, limit=limit, shards=shard_list, of=of)

    claimed = 0
    try:
        while limit is None or claimed < limit:
            # Enough for every worker to have a full run, then split so each
            # one gets a share -- see _units.
            want = chunk_dicom() * size
            if limit is not None:
                want = min(want, limit - claimed)
            with hive_cursor() as cursor:
                records = claim_chunk(cursor, prefixes, want, check_settled)
            if not records:
                break
            for unit in _units(records, size):
                work.put(unit)
            claimed += len(records)
    finally:
        work.join()
        for _ in threads:
            work.put(None)
        for thread in threads:
            thread.join(timeout=5)
        beat.stop()

    (log.info if claimed else log.debug)(
        "intake_drain_finished",
        workers=size,
        claimed=claimed,
        done=tally["done"],
        failed=tally["failed"],
    )
    return {**tally, "claimed": claimed, "workers": size}
