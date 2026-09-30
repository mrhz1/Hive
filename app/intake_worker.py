import hashlib
import json
import os
import queue
import shutil
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from app import deid, intake
from app.audit import record_audit
from app.crud import patients as patients_crud
from app.db import authoritative, hive_cursor
from app.embed import embed_metadata, generated_facts
from app.logging_setup import get_logger

log = get_logger(__name__)

HEARTBEAT_STALE_SECONDS = float(os.environ.get("INTAKE_HEARTBEAT_STALE_SECONDS", "300"))
STATUS_EVERY_SECONDS = float(os.environ.get("INTAKE_STATUS_SECONDS", "300"))
PATIENT_WAIT_SECONDS = float(os.environ.get("INTAKE_PATIENT_WAIT_SECONDS", "30"))
PATIENT_LOCK_STALE_SECONDS = 600
SCAN = "__scan__"


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


def shard_of(relative_path, of):
    digest = hashlib.md5(relative_path.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % max(1, of)


def my_shards(shards, of):
    of = max(1, int(of))
    if shards is None:
        return set(range(of))
    return {int(s) % of for s in shards}


def worker_name():
    return f"{socket.gethostname()}-{os.getpid()}"


def is_alive(heartbeat):
    if time.time() - float(heartbeat.get("last_seen") or 0) > HEARTBEAT_STALE_SECONDS:
        return False
    if heartbeat.get("host") != socket.gethostname():
        return True
    try:
        os.kill(int(heartbeat.get("pid") or 0), 0)
    except ProcessLookupError:
        return False
    except (PermissionError, ValueError):
        return True
    return True


class Heartbeat:
    def __init__(self, shards, of, pool):
        if of <= 1:
            name = f"{socket.gethostname()}-all"
        else:
            name = f"{socket.gethostname()}-{of}-" + "_".join(str(s) for s in sorted(shards))
        self.path = intake.state_dir() / "workers" / f"{name}.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)

        old = intake.read_json(self.path)
        one_hour_ago = time.time() - 3600
        per_minute = {}
        for minute, count in (old.get("per_minute") or {}).items():
            if int(minute) >= one_hour_ago:
                per_minute[minute] = count

        self.state = {
            "name": name,
            "host": socket.gethostname(),
            "pid": os.getpid(),
            "shards": sorted(shards),
            "of": of,
            "workers": pool,
            "started_at": time.time(),
            "last_seen": time.time(),
            "status": "working",
            "current": [],
            "done": 0,
            "failed": 0,
            "set_aside": 0,
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

    def set_aside(self):
        with self.lock:
            self.state["set_aside"] += 1

    def write(self):
        with self.lock:
            self.state["last_seen"] = time.time()
            data = dict(self.state)
        try:
            intake.write_json(self.path, data)
        except OSError as e:
            log.warning("intake_heartbeat_failed", error=str(e))

    def stop(self):
        self.stopped.set()
        with self.lock:
            self.state["status"] = "idle"
            self.state["current"] = []
        self.write()


def forget_dead_workers():
    """Drop the heartbeats of workers that are gone.

    On Cloudera each Job run is a new container with a new host name, so a
    run that was killed leaves a heartbeat nothing will ever overwrite --
    still "working", still holding its files -- and the Intake page would
    report the de-identification as stopped for good.
    """
    folder = intake.state_dir() / "workers"
    if not folder.is_dir():
        return 0
    removed = 0
    for path in folder.glob("*.json"):
        data = intake.read_json(path)
        if data and is_alive(data):
            continue
        path.unlink(missing_ok=True)
        removed += 1
    if removed:
        log.info("intake_dead_workers_forgotten", count=removed)
    return removed


def read_heartbeats():
    heartbeats = []
    folder = intake.state_dir() / "workers"
    if not folder.is_dir():
        return heartbeats
    for path in sorted(folder.glob("*.json")):
        data = intake.read_json(path)
        if data:
            heartbeats.append(data)
    return heartbeats


class PatientCreator:
    def __init__(self):
        self.lock_dir = intake.state_dir() / "patients"
        self.queue = queue.Queue()
        self.seen = set()
        self.seen_lock = threading.Lock()
        self.thread = threading.Thread(target=self.loop, name="intake-patients", daemon=True)
        self.thread.start()

    def add(self, code):
        # Only dedupes codes still waiting in the queue: a code finished again
        # after it was handled is queued again, so its new files are attached.
        if not code:
            return
        with self.seen_lock:
            if code in self.seen:
                return
            self.seen.add(code)
        self.queue.put(code)

    def taken(self, code):
        with self.seen_lock:
            self.seen.discard(code)

    def scan(self):
        self.queue.put(SCAN)

    def forget(self):
        with self.seen_lock:
            self.seen.clear()

    def wait(self, timeout):
        deadline = time.time() + timeout
        pause = threading.Event()
        while self.queue.unfinished_tasks and time.time() < deadline:
            pause.wait(0.1)
        return self.queue.unfinished_tasks == 0

    def loop(self):
        while True:
            code = self.queue.get()
            try:
                if code == SCAN:
                    self.add_missing()
                else:
                    self.taken(code)
                    self.create(code)
            except Exception as e:
                log.exception("intake_patient_create_failed", code=code, error=str(e))
                with self.seen_lock:
                    self.seen.discard(code)
            finally:
                self.queue.task_done()

    def add_missing(self):
        root = intake.deidentified_root()
        if not root.is_dir():
            return
        codes = sorted(d.name for d in root.iterdir() if d.is_dir() and not d.name.startswith("."))
        with hive_cursor() as cursor:
            existing = patients_crud.existing_ids(cursor, codes)
            waiting = {item["code"] for item in intake.available_codes(cursor)}
        missing = [c for c in codes if c not in existing or c in waiting]
        if missing:
            log.info("intake_patients_missing", count=len(missing))
        for code in missing:
            self.add(code)

    def take_lock(self, lock_file):
        for _ in range(2):
            try:
                fd = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, worker_name().encode())
                os.close(fd)
                return True
            except FileExistsError:
                try:
                    age = time.time() - lock_file.stat().st_mtime
                except OSError:
                    continue
                if age < PATIENT_LOCK_STALE_SECONDS:
                    return False
                lock_file.unlink(missing_ok=True)
        return False

    def create(self, code):
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        lock_file = self.lock_dir / code
        if not self.take_lock(lock_file):
            return
        try:
            with hive_cursor() as cursor:
                with authoritative(cursor):
                    exists = patients_crud.get_patient(cursor, code) is not None
                if not exists:
                    patients_crud.create_empty_patient(cursor, code)
                with authoritative(cursor):
                    application, created, attached = intake.attach_to_draft(cursor, code)
            if not exists:
                record_audit(
                    action="CREATE",
                    entity_type="patient",
                    entity_id=code,
                    user_id=intake.INTAKE_ACTOR,
                    old_values=None,
                    new_values={"id": code},
                )
                log.info("intake_patient_created", code=code)
            if created:
                record_audit(
                    action="CREATE",
                    entity_type="patient_application",
                    entity_id=application.id,
                    user_id=intake.INTAKE_ACTOR,
                    old_values=None,
                    new_values={"patient_id": code, "status": "draft"},
                )
            if attached:
                log.info(
                    "intake_files_filed",
                    code=code,
                    application_id=application.id,
                    attached=attached,
                )
        finally:
            lock_file.unlink(missing_ok=True)


_creators = {}
_creators_lock = threading.Lock()


def patient_creator():
    with _creators_lock:
        key = str(intake.state_dir())
        if key not in _creators:
            _creators[key] = PatientCreator()
        return _creators[key]


@dataclass
class Task:
    path: Path
    relative_path: str
    code: str
    extension: str

    @property
    def name(self):
        return self.path.name


def is_dicom(task):
    return (task.extension or "").lower() in ("dcm", "dicom")


def split_into_runs(tasks, workers=1):
    workers = max(1, workers)
    dicoms = [t for t in tasks if is_dicom(t)]
    documents = [t for t in tasks if not is_dicom(t)]

    runs = []

    step = max(1, min(chunk_dicom(), -(-len(dicoms) // workers)))
    for i in range(0, len(dicoms), step):
        part = dicoms[i : i + step]
        runs.append((part, len(part)))

    step = max(1, min(chunk_documents(), -(-len(documents) // workers)))
    for i in range(0, len(documents), step):
        runs.append((documents[i : i + step], 1))

    return runs


def run_pipeline(tasks, ocr_batch, workdir):
    input_dir = workdir / "in"
    output_dir = workdir / "out"
    shutil.rmtree(workdir, ignore_errors=True)
    input_dir.mkdir(parents=True)

    links = {}
    results = {}
    for n, task in enumerate(tasks):
        if not task.path.is_file():
            results[n] = deid.DeidError("the file is no longer in the incoming folder")
            continue
        link = input_dir / f"f{n:05d}.{(task.extension or 'bin').lower()}"
        link.symlink_to(task.path.resolve())
        links[str(link)] = n

    if links:
        env = worker_env() or {}
        env["DEID_OCR_BATCH_SIZE"] = str(ocr_batch)
        output = deid.run_pipeline_many([Path(p) for p in links], output_dir, env=env)
        for link, n in links.items():
            results[n] = output.get(link, deid.DeidError("no result"))
    return results


def redact_unit(tasks, ocr_batch, workdir):
    results = run_pipeline(tasks, ocr_batch, workdir / "run")
    if len(tasks) > 1:
        for n, task in enumerate(tasks):
            if isinstance(results.get(n), Exception):
                single = run_pipeline([task], 1, workdir / "one")
                results[n] = single.get(0)
    outcomes = [finish(task, results.get(n)) for n, task in enumerate(tasks)]
    shutil.rmtree(workdir, ignore_errors=True)
    return outcomes


def pending_file(task):
    digest = hashlib.md5(task.relative_path.encode("utf-8")).hexdigest()
    return intake.state_dir() / "pending" / f"{digest}.json"


def finish(task, result):
    method = None
    if isinstance(result, deid.Produced):
        method = result.method
        result = result.path

    if not isinstance(result, Path):
        detail = str(result) if result is not None else "no result"
        log.error("intake_file_failed", path=task.relative_path, error=detail)
        candidate = intake.Candidate(
            path=task.path,
            relative_path=task.relative_path,
            extension=task.extension,
            size=0,
            detection=intake.detect(task.relative_path),
        )
        try:
            intake.set_aside(candidate, intake.failed_root(), intake.REDACTION_FAILED, detail)
        except OSError as e:
            log.error("intake_file_move_failed", path=task.relative_path, error=str(e))
        return "failed"

    target_dir = intake.deidentified_root() / task.code / Path(task.relative_path).parent
    target_dir.mkdir(parents=True, exist_ok=True)
    stem = deid.unique_output_stem(target_dir, task.code, result.suffix)
    final = target_dir / f"{stem}{result.suffix}"
    partial = Path(str(final) + intake.PARTIAL_SUFFIX)
    original = intake.original_root() / task.relative_path

    pending = pending_file(task)
    intake.write_json(
        pending,
        {
            "relative_path": task.relative_path,
            "code": task.code,
            "partial": str(partial),
            "final": str(final),
            "original": str(original),
            "method": method,
            "original_name": task.name,
        },
    )

    try:
        file_type = result.suffix.lstrip(".").lower()
        facts = generated_facts(
            patient_id=task.code,
            output_name=final.name,
            output_type=file_type,
            by="intake",
            source_name=task.name,
        )
        embed_metadata(result, file_type, facts)
        os.replace(result, partial)
        original = intake.move_file(task.path, original)
        complete(pending, original)
    except Exception as e:
        log.exception("intake_file_finish_failed", path=task.relative_path, error=str(e))
        return "failed"
    return "done"


def complete(pending, original=None):
    info = intake.read_json(pending)
    partial = Path(info["partial"])
    final = Path(info["final"])
    original = Path(original or info["original"])
    intake.write_json(
        Path(str(final) + intake.SIDECAR_SUFFIX),
        {
            "original_path": str(original),
            "original_name": info.get("original_name"),
            "relative_path": info["relative_path"],
            "code": info["code"],
            "method": info.get("method"),
            "created_at": time.time(),
        },
    )
    os.replace(partial, final)
    pending.unlink(missing_ok=True)


def clean_up(shards=None, of=1):
    shards = my_shards(shards, of)
    folder = intake.state_dir() / "pending"
    if not folder.is_dir():
        return 0
    fixed = 0
    for pending in folder.glob("*.json"):
        info = intake.read_json(pending)
        if not info:
            pending.unlink(missing_ok=True)
            continue
        if shard_of(info["relative_path"], of) not in shards:
            continue
        partial = Path(info["partial"])
        incoming = intake.intake_root() / info["relative_path"]
        original = Path(info["original"])
        try:
            if incoming.is_file():
                partial.unlink(missing_ok=True)
                pending.unlink(missing_ok=True)
            elif partial.is_file() and original.is_file():
                complete(pending)
            else:
                pending.unlink(missing_ok=True)
            fixed += 1
        except OSError as e:
            log.error("intake_cleanup_failed", pending=str(pending), error=str(e))
    if fixed:
        log.warning("intake_cleanup_done", files=fixed)
    return fixed


def write_status(root):
    remaining = 0
    for _ in intake.walk(root):
        remaining += 1
    intake.write_json(
        intake.state_dir() / "status.json",
        {"remaining": remaining, "counted_at": time.time()},
    )
    return remaining


def status_loop(root, stop):
    while True:
        try:
            write_status(root)
        except Exception as e:
            log.warning("intake_status_failed", error=str(e))
        if stop.wait(STATUS_EVERY_SECONDS):
            return


def process(limit=None, pool_size=None, shards=None, of=1, root=None):
    root = root or intake.intake_root()
    pool = pool_size or safe_worker_count()
    shards = my_shards(shards, of)
    is_main = 0 in shards

    totals = {"done": 0, "failed": 0, "set_aside": 0, "skipped_unsettled": 0}
    totals_lock = threading.Lock()
    work = queue.Queue(maxsize=pool)
    if is_main:
        forget_dead_workers()
    heartbeat = Heartbeat(shards, of, pool).start()
    creator = patient_creator()
    creator.forget()
    if is_main:
        creator.scan()

    stop_status = threading.Event()
    status_thread = None
    if is_main:
        status_thread = threading.Thread(
            target=status_loop, args=(root, stop_status), name="intake-status", daemon=True
        )
        status_thread.start()

    def worker(n):
        workdir = intake.state_dir() / "work" / f"{worker_name()}-t{n}"
        while True:
            item = work.get()
            try:
                if item is None:
                    return
                tasks, ocr_batch = item
                heartbeat.working_on([t.name for t in tasks])
                outcomes = redact_unit(tasks, ocr_batch, workdir)
                done = outcomes.count("done")
                failed = len(outcomes) - done
                heartbeat.finished(done, failed)
                with totals_lock:
                    totals["done"] += done
                    totals["failed"] += failed
                for task, outcome in zip(tasks, outcomes):
                    if outcome == "done":
                        creator.add(task.code)
            except Exception as e:
                log.exception("intake_chunk_error", error=str(e))
            finally:
                work.task_done()

    threads = []
    for n in range(pool):
        t = threading.Thread(target=worker, args=(n,), name=f"intake-worker-{n}", daemon=True)
        t.start()
        threads.append(t)

    overrides = intake.load_overrides()
    batch = []
    queued = 0
    try:
        for path in intake.walk(root):
            if limit is not None and queued >= limit:
                break
            relative = path.relative_to(root).as_posix()
            if shard_of(relative, of) not in shards:
                continue
            if not intake.is_settled(path):
                totals["skipped_unsettled"] += 1
                continue

            candidate = intake.classify(path, root, overrides)
            if candidate.reason is None and intake.is_duplicate(candidate):
                candidate.reason = intake.DUPLICATE
                candidate.detail = "the same file is already in the original folder"
            if candidate.reason:
                intake.set_aside(candidate, intake.attention_root(), candidate.reason, candidate.detail)
                heartbeat.set_aside()
                totals["set_aside"] += 1
                continue

            if relative in overrides:
                intake.remove_override(relative)
            batch.append(Task(path, relative, candidate.code, candidate.extension))
            queued += 1
            if len(batch) >= chunk_dicom() * pool:
                for run in split_into_runs(batch, pool):
                    work.put(run)
                batch = []
        if batch:
            for run in split_into_runs(batch, pool):
                work.put(run)
    finally:
        work.join()
        for _ in threads:
            work.put(None)
        for t in threads:
            t.join(timeout=5)
        heartbeat.stop()
        if not creator.wait(PATIENT_WAIT_SECONDS):
            log.warning("intake_patients_pending", waited_seconds=PATIENT_WAIT_SECONDS)
        if is_main:
            try:
                intake.prune_empty_folders(root)
            except Exception as e:
                log.warning("intake_prune_failed", error=str(e))
        if status_thread:
            stop_status.set()
            status_thread.join(timeout=5)
            try:
                write_status(root)
            except Exception as e:
                log.warning("intake_status_failed", error=str(e))

    log.info("intake_process_finished", workers=pool, **totals)
    return dict(totals, workers=pool)
