import json
import os
import queue
import shutil
import socket
import threading
import time
from pathlib import Path

from app import deid, intake
from app.crud import intake_files as crud
from app.db import hive_cursor
from app.embed import embed_metadata, generated_facts
from app.logging_setup import get_logger
from app.schemas import IntakeFileUpdate  # noqa: F401

log = get_logger(__name__)

HEARTBEAT_STALE_SECONDS = float(os.environ.get("INTAKE_HEARTBEAT_STALE_SECONDS", "300"))
PREFIXES = [f"{n:02x}" for n in range(256)]


def workers():
    return max(1, int(os.environ.get("DEID_WORKERS", "1")))


def worker_cpu_threads():
    return os.environ.get("DEID_WORKER_CPU_THREADS")


def worker_memory_gb():
    value = os.environ.get("DEID_WORKER_MEMORY_GB")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def chunk_dicom():
    return max(1, int(os.environ.get("DEID_CHUNK_DICOM", "40")))


def chunk_documents():
    return max(1, int(os.environ.get("DEID_CHUNK_DOCUMENTS", "4")))


def worker_env():
    threads = worker_cpu_threads()
    if not threads:
        return None
    return {
        "OCR_CPU_THREADS": threads,
        "OMP_NUM_THREADS": threads,
        "MKL_NUM_THREADS": threads,
    }


def free_memory_gb():
    try:
        pages = os.sysconf("SC_AVPHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
    except (ValueError, OSError, AttributeError):
        return None
    return pages * page_size / (1024**3)


def safe_worker_count():
    wanted = workers()
    per_worker = worker_memory_gb()
    if not per_worker:
        return wanted
    available = free_memory_gb()
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


def shard_prefixes(shards=None, of=1):
    of = max(1, int(of))
    if shards is None:
        mine = set(range(of))
    else:
        mine = {int(s) % of for s in shards}
    return [p for p in PREFIXES if int(p, 16) % of in mine]


def worker_name():
    return f"{socket.gethostname()}-{os.getpid()}"


class Journal:
    def __init__(self, root, name):
        self.path = root / ".intake" / "journal" / f"{name}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def append(self, result):
        line = json.dumps(result, separators=(",", ":")) + "\n"
        with self.lock:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())

    def clear(self):
        with self.lock:
            self.path.unlink(missing_ok=True)

    @staticmethod
    def read(path):
        results = []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return results
        for line in lines:
            try:
                results.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return results


def is_process_running(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def is_journal_abandoned(path, root):
    host, _, pid = path.stem.rpartition("-t")[0].rpartition("-")
    try:
        pid = int(pid)
    except ValueError:
        return False
    if host == socket.gethostname():
        return not is_process_running(pid)
    heartbeat_file = root / ".intake" / "workers" / f"{host}-{pid}.json"
    try:
        return time.time() - heartbeat_file.stat().st_mtime > HEARTBEAT_STALE_SECONDS
    except OSError:
        return True


def replay_journals(cursor, root):
    journal_dir = root / ".intake" / "journal"
    if not journal_dir.is_dir():
        return 0
    count = 0
    for path in sorted(journal_dir.glob("*.jsonl")):
        if not is_journal_abandoned(path, root):
            continue
        results = Journal.read(path)
        if results:
            publish_results(cursor, results)
            count += len(results)
        path.unlink(missing_ok=True)
    if count:
        log.warning("intake_journal_replayed", results=count)
    return count


def publish_results(cursor, results, attempts=4):
    for attempt in range(1, attempts + 1):
        try:
            crud.apply_results(cursor, results)
            return
        except Exception as e:
            if attempt == attempts:
                raise
            wait = 2**attempt
            log.warning("intake_publish_retry", attempt=attempt, wait_seconds=wait, error=str(e))
            time.sleep(wait)


class Heartbeat:
    def __init__(self, root, shards, of, pool):
        if of <= 1:
            name = f"{socket.gethostname()}-all"
        else:
            name = f"{socket.gethostname()}-{of}-" + "_".join(str(s) for s in shards)
        self.path = root / ".intake" / "workers" / f"{name}.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)

        old = {}
        try:
            old = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            pass

        one_hour_ago = time.time() - 3600
        per_minute = {}
        for minute, count in (old.get("per_minute") or {}).items():
            if int(minute) >= one_hour_ago:
                per_minute[minute] = count

        self.state = {
            "name": name,
            "host": socket.gethostname(),
            "pid": os.getpid(),
            "shards": shards,
            "of": of,
            "workers": pool,
            "started_at": time.time(),
            "last_seen": time.time(),
            "status": "working",
            "current": [],
            "done": int(old.get("done", 0)),
            "failed": int(old.get("failed", 0)),
            "per_minute": per_minute,
        }
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self.loop, name="intake-heartbeat", daemon=True)

    def start(self):
        self.write()
        self.thread.start()
        return self

    def loop(self):
        while not self.stopped.wait(5):
            self.write()

    def working_on(self, names):
        with self.lock:
            self.state["current"] = names[:10]

    def finished(self, done, failed):
        minute = str(int(time.time() // 60 * 60))
        one_hour_ago = time.time() - 3600
        with self.lock:
            self.state["done"] += done
            self.state["failed"] += failed
            per_minute = self.state["per_minute"]
            per_minute[minute] = per_minute.get(minute, 0) + done + failed
            for key in list(per_minute):
                if int(key) < one_hour_ago:
                    del per_minute[key]

    def write(self):
        with self.lock:
            self.state["last_seen"] = time.time()
            data = json.dumps(self.state)
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text(data)
            tmp.replace(self.path)
        except OSError as e:
            log.warning("intake_heartbeat_failed", error=str(e))

    def stop(self):
        self.stopped.set()
        with self.lock:
            self.state["status"] = "idle"
            self.state["current"] = []
        self.write()


def read_heartbeats(root):
    heartbeats = []
    folder = root / ".intake" / "workers"
    if not folder.is_dir():
        return heartbeats
    for path in sorted(folder.glob("*.json")):
        try:
            heartbeats.append(json.loads(path.read_text()))
        except (OSError, json.JSONDecodeError):
            continue
    return heartbeats


class RedactionError(Exception):
    pass


def get_root(record):
    depth = len(Path(record.relative_path).parts)
    try:
        return Path(record.source_path).parents[depth - 1]
    except IndexError:
        return intake.intake_root()


def is_ready(record):
    source = Path(record.source_path)
    if intake.batch_is_marked_done(source.parent):
        return True
    return intake.is_settled(source)


def is_dicom(record):
    return (record.file_extension or "").lower() in ("dcm", "dicom")


def split_into_runs(records, workers=1):
    workers = max(1, workers)
    dicoms = [r for r in records if is_dicom(r)]
    documents = [r for r in records if not is_dicom(r)]

    runs = []

    step = max(1, min(chunk_dicom(), -(-len(dicoms) // workers)))
    for i in range(0, len(dicoms), step):
        part = dicoms[i : i + step]
        runs.append((part, len(part)))

    step = max(1, min(chunk_documents(), -(-len(documents) // workers)))
    for i in range(0, len(documents), step):
        runs.append((documents[i : i + step], 1))

    return runs


def redact_unit(records, ocr_batch, workdir):
    results = run_pipeline(records, ocr_batch, workdir / "run")
    if len(records) > 1:
        for record in records:
            if isinstance(results.get(record.id), Exception):
                results.update(run_pipeline([record], 1, workdir / "one"))
    outcomes = [make_outcome(record, results.get(record.id)) for record in records]
    shutil.rmtree(workdir, ignore_errors=True)
    return outcomes


def run_pipeline(records, ocr_batch, workdir):
    input_dir = workdir / "in"
    output_dir = workdir / "out"
    shutil.rmtree(workdir, ignore_errors=True)
    input_dir.mkdir(parents=True)

    links = {}
    results = {}
    for record in records:
        source = Path(record.source_path)
        if not source.is_file():
            results[record.id] = deid.DeidError("the file is no longer at the path it was found at")
            continue
        link = input_dir / f"{record.id}.{(record.file_extension or 'bin').lower()}"
        link.symlink_to(source)
        links[str(link)] = record.id

    if links:
        env = worker_env() or {}
        env["DEID_OCR_BATCH_SIZE"] = str(ocr_batch)
        output = deid.run_pipeline_many([Path(p) for p in links], output_dir, env=env)
        for link, record_id in links.items():
            results[record_id] = output.get(link, deid.DeidError("no result"))
    return results


def move_outputs(produced, record, code):
    target_dir = intake.mirrored_dir(record.relative_path, get_root(record))
    target_dir.mkdir(parents=True, exist_ok=True)
    new_stem = deid.unique_output_stem(target_dir, code, produced.suffix)

    old_stem = produced.stem
    for path in sorted(produced.parent.iterdir()):
        if path.is_file() and path.name.startswith(old_stem):
            new_name = new_stem + path.name[len(old_stem) :]
            shutil.move(str(path), str(target_dir / new_name))
    return target_dir / f"{new_stem}{produced.suffix}"


def redact_records(records, workdir):
    outcomes = []
    for run, ocr_batch in split_into_runs(records):
        outcomes.extend(redact_unit(run, ocr_batch, workdir))
    return outcomes


def failed_outcome(record, detail):
    return {
        "id": record.id,
        "status": "failed",
        "output_path": None,
        "output_name": None,
        "detail": detail,
    }


def make_outcome(record, result):
    code = record.patient_code or ""
    method = None
    if isinstance(result, deid.Produced):
        method = result.method
        result = result.path

    if not isinstance(result, Path):
        detail = str(result) if result is not None else "no result"
        log.error("intake_file_failed", file_id=record.id, error=detail)
        return failed_outcome(record, detail)

    try:
        final = move_outputs(result, record, code)
        file_type = final.suffix.lstrip(".").lower()
        facts = generated_facts(
            patient_id=code,
            output_name=final.name,
            output_type=file_type,
            by="intake sweep",
            source_name=record.file_name,
        )
        embed_metadata(final, file_type, facts)
    except Exception as e:
        log.exception("intake_file_crashed", file_id=record.id, error=str(e))
        return failed_outcome(record, f"unexpected: {e}")

    return {
        "id": record.id,
        "status": "done",
        "output_path": str(final),
        "output_name": final.name,
        "detail": method,
    }


def redact_one(record):
    workdir = get_root(record) / ".intake" / "work" / f"{worker_name()}-one"
    outcome = redact_records([record], workdir)[0]
    with hive_cursor() as cursor:
        publish_results(cursor, [outcome])
    return outcome["status"] == "done"


def claim_chunk(cursor, prefixes, size, check_settled=True):
    records = crud.list_queued(cursor, prefixes, size)
    if check_settled:
        records = [r for r in records if is_ready(r)]
    if records:
        crud.set_status_many(cursor, [r.id for r in records], "processing")
    return records


def recover(cursor, root, prefixes):
    replay_journals(cursor, root)
    requeued = crud.requeue_processing(cursor, prefixes)
    if requeued:
        log.warning("intake_rows_recovered", requeued=requeued)
    return requeued


def drain(limit=None, pool_size=None, check_settled=True, shards=None, of=1, root=None):
    root = root or intake.intake_root()
    pool = pool_size or safe_worker_count()
    prefixes = shard_prefixes(shards, of)
    my_shards = sorted({int(p, 16) % max(1, of) for p in prefixes})

    totals = {"done": 0, "failed": 0}
    totals_lock = threading.Lock()
    work = queue.Queue(maxsize=pool)
    heartbeat = Heartbeat(root, my_shards, of, pool).start()

    def worker(n):
        name = f"{worker_name()}-t{n}"
        journal = Journal(root, name)
        workdir = root / ".intake" / "work" / name
        while True:
            item = work.get()
            try:
                if item is None:
                    return
                records, ocr_batch = item
                heartbeat.working_on([r.file_name for r in records])
                outcomes = redact_unit(records, ocr_batch, workdir)
                for outcome in outcomes:
                    journal.append(outcome)
                with hive_cursor() as cursor:
                    publish_results(cursor, outcomes)
                journal.clear()

                done = len([o for o in outcomes if o["status"] == "done"])
                failed = len(outcomes) - done
                heartbeat.finished(done, failed)
                with totals_lock:
                    totals["done"] += done
                    totals["failed"] += failed
            except Exception as e:
                log.exception("intake_chunk_error", error=str(e))
            finally:
                work.task_done()

    threads = []
    for n in range(pool):
        t = threading.Thread(target=worker, args=(n,), name=f"intake-worker-{n}", daemon=True)
        t.start()
        threads.append(t)

    log.debug("intake_drain_started", workers=pool, limit=limit, shards=my_shards, of=of)

    claimed = 0
    try:
        while limit is None or claimed < limit:
            count = chunk_dicom() * pool
            if limit is not None:
                count = min(count, limit - claimed)
            with hive_cursor() as cursor:
                records = claim_chunk(cursor, prefixes, count, check_settled)
            if not records:
                break
            for run in split_into_runs(records, pool):
                work.put(run)
            claimed += len(records)
    finally:
        work.join()
        for _ in threads:
            work.put(None)
        for t in threads:
            t.join(timeout=5)
        heartbeat.stop()

    if claimed:
        log.info("intake_drain_finished", workers=pool, claimed=claimed, done=totals["done"], failed=totals["failed"])
    else:
        log.debug("intake_drain_finished", workers=pool, claimed=claimed, done=totals["done"], failed=totals["failed"])

    return {"done": totals["done"], "failed": totals["failed"], "claimed": claimed, "workers": pool}
