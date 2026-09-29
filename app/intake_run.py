import fcntl
import os
import threading
import time
from pathlib import Path
from typing import List, Optional

from app import intake, intake_worker
from app.crud import intake_files as crud
from app.db import hive_cursor
from app.logging_setup import get_logger

log = get_logger(__name__)

FULL_SWEEP_HOURS = float(os.environ.get("INTAKE_FULL_SWEEP_HOURS", "24"))

LOCK_FILE = "run.lock"
LAST_SWEEP_FILE = "last_swept"
LAST_FULL_SWEEP_FILE = "last_full_sweep"
MIRROR_CHECK_FILE = ".intake-mirror"

IDLE = "idle"
ARRIVING = "arriving"
BUSY = "busy"
RAN = "ran"


def make_result(outcome, detail=""):
    return {
        "outcome": outcome,
        "detail": detail,
        "swept": 0,
        "skipped": 0,
        "conflicts": 0,
        "redacted": 0,
        "failed": 0,
        "markers": [],
    }


def acquire_lock(root: Path, name: str = LOCK_FILE):
    state_dir = root / ".intake"
    state_dir.mkdir(parents=True, exist_ok=True)
    f = open(state_dir / name, "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.close()
        return None
    f.write(str(os.getpid()))
    f.flush()
    return f


def release_lock(f):
    fcntl.flock(f, fcntl.LOCK_UN)
    f.close()


def read_time(root: Path, name: str):
    try:
        return float((root / ".intake" / name).read_text().strip())
    except (OSError, ValueError):
        return None


def save_time(root: Path, name: str, value: float):
    state_dir = root / ".intake"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / name).write_text(repr(value))


def find_markers(root: Path, since: Optional[float] = None) -> List[Path]:
    found = []
    for folder, _, names in intake.walk_folders(root, since):
        if intake.BATCH_MARKER in names:
            found.append(folder / intake.BATCH_MARKER)
    return found


def get_last_change(root: Path, since: Optional[float] = None):
    latest = None
    for folder, folder_time, names in intake.walk_folders(root, since):
        if since is not None:
            if latest is None or folder_time > latest:
                latest = folder_time
        for name in names:
            if name.startswith(".") or name == intake.BATCH_MARKER:
                continue
            try:
                modified = intake.last_touched((folder / name).stat())
            except OSError:
                continue
            if latest is None or modified > latest:
                latest = modified
    return latest


def push_state(root: Path, quiet_seconds: Optional[float] = None) -> str:
    if quiet_seconds is None:
        quiet_seconds = intake.settle_seconds()

    last_sweep = read_time(root, LAST_SWEEP_FILE)
    changed = get_last_change(root, since=last_sweep)
    if changed is None:
        return IDLE

    if find_markers(root, since=last_sweep):
        return RAN

    if last_sweep is not None and changed <= last_sweep:
        return IDLE

    if time.time() - changed < quiet_seconds:
        return ARRIVING
    return RAN


def recover(cursor, root: Path, prefixes: List[str]) -> int:
    requeued = intake_worker.recover(cursor, root, prefixes)

    check_file = intake.deidentified_root(root) / MIRROR_CHECK_FILE
    if check_file.exists():
        return requeued

    my_prefixes = set(prefixes)
    redo = []
    for record in crud.list_files(cursor, status="done"):
        if record.id[:2] not in my_prefixes:
            continue
        output_missing = not record.output_path or not Path(record.output_path).is_file()
        if output_missing and Path(record.source_path).is_file():
            redo.append(
                {
                    "id": record.id,
                    "status": "queued",
                    "output_path": None,
                    "output_name": None,
                    "detail": "redone: its redacted copy was missing",
                }
            )
    if redo:
        crud.apply_results(cursor, redo)
        log.warning("intake_missing_copies_requeued", requeued=len(redo))

    check_file.parent.mkdir(parents=True, exist_ok=True)
    check_file.write_text("delete this folder and every copy in it is redone\n")
    return requeued + len(redo)


def drain_queue(limit, root, shards, of):
    drained = intake_worker.drain(limit=limit, check_settled=False, shards=shards, of=of, root=root)
    if not drained["claimed"]:
        return make_result(IDLE, "nothing new has arrived")
    result = make_result(RAN, "finished what an earlier run left queued")
    result["redacted"] = drained["done"]
    result["failed"] = drained["failed"]
    return result


def run_once(
    root: Optional[Path] = None,
    quiet_seconds: Optional[float] = None,
    limit: Optional[int] = None,
    shards: Optional[List[int]] = None,
    of: int = 1,
) -> dict:
    root = root or intake.intake_root()
    prefixes = intake_worker.shard_prefixes(shards, of)

    does_sweep = False
    for p in prefixes:
        if int(p, 16) % max(1, of) == 0:
            does_sweep = True
            break

    lock_name = LOCK_FILE
    if shards is not None and of > 1:
        lock_name = f"run-{of}-" + "_".join(str(s) for s in sorted(shards)) + ".lock"

    lock = acquire_lock(root, lock_name)
    if lock is None:
        return make_result(BUSY, "another run is still working")

    try:
        with hive_cursor() as cursor:
            recover(cursor, root, prefixes)

        if not does_sweep:
            return drain_queue(limit, root, shards, of)

        state = push_state(root, quiet_seconds)
        if state == ARRIVING:
            return make_result(ARRIVING, "files are still being copied in")

        last_sweep = read_time(root, LAST_SWEEP_FILE)
        last_full = read_time(root, LAST_FULL_SWEEP_FILE)
        full = last_sweep is None or last_full is None or time.time() - last_full >= FULL_SWEEP_HOURS * 3600
        if state == IDLE and not full:
            return drain_queue(limit, root, shards, of)

        since = None if full else last_sweep
        markers = find_markers(root, since=since)
        changed = get_last_change(root, since=since)

        with hive_cursor() as cursor:
            swept = intake.sweep(cursor, root=root, dry_run=False, touched_since=last_sweep, full=full)

        if changed is not None:
            save_time(root, LAST_SWEEP_FILE, max(changed, last_sweep or changed))
        if full:
            save_time(root, LAST_FULL_SWEEP_FILE, time.time())

        for marker in markers:
            try:
                marker.unlink()
            except OSError:
                log.warning("intake_marker_not_removed", path=str(marker))

        drained = intake_worker.drain(limit=limit, check_settled=False, shards=shards, of=of, root=root)
    finally:
        release_lock(lock)

    if not swept.recorded and not swept.retried and not drained["claimed"]:
        return make_result(IDLE, "nothing new has arrived")

    result = make_result(RAN)
    result["swept"] = swept.recorded
    result["skipped"] = swept.count(intake.SKIPPED)
    result["conflicts"] = swept.count(intake.CONFLICT)
    result["redacted"] = drained["done"]
    result["failed"] = drained["failed"]
    result["markers"] = [str(m) for m in markers]

    log.info(
        "intake_run_finished",
        root=str(root),
        swept=result["swept"],
        skipped=result["skipped"],
        conflicts=result["conflicts"],
        redacted=result["redacted"],
        failed=result["failed"],
    )
    return result


def watch(
    root: Optional[Path] = None,
    every_seconds: float = 60,
    quiet_seconds: Optional[float] = None,
    stop=None,
    shards: Optional[List[int]] = None,
    of: int = 1,
):
    if stop is None:
        stop = threading.Event()
    log.info("intake_watch_started", every_seconds=every_seconds)
    while not stop.is_set():
        try:
            result = run_once(root, quiet_seconds, shards=shards, of=of)
            if result["outcome"] == RAN:
                log.info(
                    "intake_watch_ran",
                    outcome=result["outcome"],
                    detail=result["detail"],
                    swept=result["swept"],
                    skipped=result["skipped"],
                    conflicts=result["conflicts"],
                    redacted=result["redacted"],
                    failed=result["failed"],
                )
        except Exception as e:
            log.exception("intake_watch_error", error=str(e))
        stop.wait(every_seconds)
