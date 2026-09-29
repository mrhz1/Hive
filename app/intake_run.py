"""Start de-identification by itself once a push has finished landing.

Meant to be called often -- every minute from a scheduled Job, or in a loop
by `scripts/intake_run.py --watch`. Most calls find nothing to do and cost
one walk of the folder. The expensive work starts only when a push is
complete:

- **the sender said so**, by dropping a `batch.done` marker, or
- **the folder has gone quiet**: nothing in it has changed for
  INTAKE_SETTLE_SECONDS, which is what the end of a copy looks like from the
  outside.

Then it sweeps (classify and queue) and drains the queue (redact), and hands
back a summary. A push still in progress is left alone: taking a folder
half-copied would record the files that had arrived and leave the rest for a
later batch, splitting one delivery across two.
"""

import fcntl
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from app import intake, intake_worker
from app.db import hive_cursor
from app.logging_setup import get_logger

log = get_logger(__name__)

LOCK_NAME = "run.lock"

# Outcomes a run can report.
IDLE = "idle"
ARRIVING = "arriving"
BUSY = "busy"
RAN = "ran"


@dataclass
class RunResult:
    outcome: str
    detail: str = ""
    swept: int = 0
    skipped: int = 0
    conflicts: int = 0
    redacted: int = 0
    failed: int = 0
    markers: List[str] = field(default_factory=list)


def _state_dir(root: Path) -> Path:
    # `.intake` is one of the folders a sweep never walks into.
    return root / ".intake"


def _lock_name(shards: Optional[List[int]], of: int) -> str:
    if shards is None or of <= 1:
        return LOCK_NAME
    return f"run-{of}-" + "_".join(str(k) for k in sorted(shards)) + ".lock"


@contextmanager
def exclusive(root: Path, name: str = LOCK_NAME):
    """Hold the run lock, or yield False if another run already has it.

    A run can outlast the gap to the next one -- a thousand files take
    hours -- and two runs at once would both drain the same queue. The lock
    is an OS file lock, so a run that dies releases it with its process; no
    stale lock file needs clearing by hand.
    """
    state = _state_dir(root)
    state.mkdir(parents=True, exist_ok=True)
    handle = open(state / name, "w")
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        handle.write(str(os.getpid()))
        handle.flush()
        try:
            yield True
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        handle.close()


def markers(root: Path, since: Optional[float] = None) -> List[Path]:
    """Every `batch.done` the sender has dropped in a folder that changed.

    Dropping one changes its folder's time, so a walk of changed folders
    finds it -- without searching the mirror's millions of files for it.
    """
    found = []
    for here, _, names in intake.walk_folders(root, since):
        if intake.BATCH_MARKER in names:
            found.append(here / intake.BATCH_MARKER)
    return found


def _is_ours(relative: Path) -> bool:
    return intake._is_reserved(relative)


def last_change(root: Path, since: Optional[float] = None) -> Optional[float]:
    """When anything that will be swept last changed -- or None if nothing
    has since `since` (or, without it, if the folder is empty)."""
    latest = None
    for here, folder_time, names in intake.walk_folders(root, since):
        if since is not None:
            latest = folder_time if latest is None else max(latest, folder_time)
        for name in names:
            if name.startswith(".") or name == intake.BATCH_MARKER:
                continue
            try:
                touched = intake.last_touched((here / name).stat())
            except OSError:
                continue
            latest = touched if latest is None else max(latest, touched)
    return latest


SWEPT_MARK = "last_swept"


def last_swept(root: Path) -> Optional[float]:
    """The folder's last-change time as of the last completed sweep."""
    try:
        return float((_state_dir(root) / SWEPT_MARK).read_text().strip())
    except (OSError, ValueError):
        return None


def _remember_swept(root: Path, changed: float) -> None:
    state = _state_dir(root)
    state.mkdir(parents=True, exist_ok=True)
    (state / SWEPT_MARK).write_text(repr(changed))


FULL_MARK = "last_full_sweep"


def full_sweep_hours() -> float:
    try:
        return float(os.environ.get("INTAKE_FULL_SWEEP_HOURS", "24"))
    except ValueError:
        return 24.0


def _full_sweep_due(root: Path) -> bool:
    """Once a day, look at every file rather than only changed folders.

    The only thing the minute-by-minute check cannot see is a file
    overwritten in place -- its folder's time does not change. This is what
    finds those.
    """
    try:
        last = float((_state_dir(root) / FULL_MARK).read_text().strip())
    except (OSError, ValueError):
        return True
    return time.time() - last >= full_sweep_hours() * 3600


def _remember_full(root: Path) -> None:
    state = _state_dir(root)
    state.mkdir(parents=True, exist_ok=True)
    (state / FULL_MARK).write_text(repr(time.time()))


def push_state(root: Path, quiet_seconds: Optional[float] = None) -> str:
    """IDLE, ARRIVING, or RAN (a finished push worth sweeping).

    "Quiet" alone is not enough to sweep on: a folder that finished landing
    last week is quiet too. Without comparing against the last sweep, every
    check re-swept an unchanged folder -- a new empty batch a minute and a
    database round-trip per file, for nothing.
    """
    quiet = intake.settle_seconds() if quiet_seconds is None else quiet_seconds

    swept = last_swept(root)
    changed = last_change(root, since=swept)
    if changed is None:
        return IDLE

    if markers(root, since=swept):
        return RAN

    if swept is not None and changed <= swept:
        return IDLE

    if time.time() - changed < quiet:
        return ARRIVING
    return RAN


MIRROR_TOKEN = ".intake-mirror"


def _mirror_token(root: Path) -> Path:
    return intake.deidentified_root(root) / MIRROR_TOKEN


def recover(cursor, root: Path, prefixes: List[str]) -> int:
    """Put back in the queue whatever an earlier run left broken.

    Only for this process's shards -- another process on another machine may
    be working the rest -- and only under this process's run lock, which
    proves none of its own workers is running:

    - outcomes a killed worker finished but never recorded are published
      from its journal, so that work is not done twice;
    - a row still `processing` was abandoned mid-redaction and goes back in
      the queue;
    - a row `done` whose redacted copy is gone is redone -- but that check
      reads every done row, so it runs only when the mirror itself has been
      cleared (its token file is missing), not every minute over millions.

    Returns how many rows were put back.
    """
    from app.crud import intake_files as crud

    requeued = intake_worker.recover(cursor, root, prefixes)

    token = _mirror_token(root)
    if token.exists():
        return requeued

    wanted = set(prefixes)
    redo = []
    for record in crud.list_files(cursor, status="done"):
        if record.id[:2] not in wanted:
            continue
        output_gone = not record.output_path or not Path(record.output_path).is_file()
        if output_gone and Path(record.source_path).is_file():
            redo.append({"id": record.id, "status": "queued", "output_path": None,
                         "output_name": None,
                         "detail": "redone: its redacted copy was missing"})
    if redo:
        crud.apply_results(cursor, redo)
        log.warning("intake_missing_copies_requeued", requeued=len(redo))

    token.parent.mkdir(parents=True, exist_ok=True)
    token.write_text("delete this folder and every copy in it is redone\n")
    return requeued + len(redo)


def run_once(
    root: Optional[Path] = None,
    quiet_seconds: Optional[float] = None,
    limit: Optional[int] = None,
    shards: Optional[List[int]] = None,
    of: int = 1,
) -> RunResult:
    """Check the folder; if a push has finished, sweep it and redact it.

    `shards` of `of` is this process's share of the work -- default all of
    it. Only the process that owns shard 0 sweeps, so several processes on
    several machines never record the same arrival twice.
    """
    root = root or intake.intake_root()
    prefixes = intake_worker.shard_prefixes(shards, of)
    sweeps = 0 in {int(p, 16) % max(1, of) for p in prefixes}

    with exclusive(root, _lock_name(shards, of)) as mine:
        if not mine:
            return RunResult(BUSY, "another run is still working")

        with hive_cursor() as cursor:
            recover(cursor, root, prefixes)

        if not sweeps:
            return _drain_only(limit, root, shards, of)

        state = push_state(root, quiet_seconds)
        if state == ARRIVING:
            return RunResult(ARRIVING, "files are still being copied in")

        previous = last_swept(root)
        full = previous is None or _full_sweep_due(root)
        if state == IDLE and not full:
            # Nothing new to sweep, but a queue left by a run that was
            # stopped part-way is still worth draining.
            return _drain_only(limit, root, shards, of)

        seen_markers = markers(root, since=None if full else previous)
        # Taken before sweeping: a file that lands mid-sweep is newer than
        # this, so the next check still sees it as new.
        changed = last_change(root, since=None if full else previous)

        with hive_cursor() as cursor:
            swept = intake.sweep(
                cursor, root=root, dry_run=False, touched_since=previous, full=full
            )

        if changed is not None:
            _remember_swept(root, max(changed, previous or changed))
        if full:
            _remember_full(root)

        # A marker is spent once its push has been swept. Left in place, the
        # next push into the same folder would be taken as finished the
        # moment its first file appeared.
        for marker in seen_markers:
            try:
                marker.unlink()
            except OSError:  # pragma: no cover - logged, harmless
                log.warning("intake_marker_not_removed", path=str(marker))

        drained = intake_worker.drain(
            limit=limit, check_settled=False, shards=shards, of=of, root=root
        )

    nothing_new = (
        not swept.recorded and not swept.retried and not drained["claimed"]
    )
    if nothing_new:
        # A sweep that found nothing is idle, whatever made it look.
        return RunResult(IDLE, "nothing new has arrived")

    result = RunResult(
        RAN,
        swept=swept.recorded,
        skipped=swept.count(intake.SKIPPED),
        conflicts=swept.count(intake.CONFLICT),
        redacted=drained["done"],
        failed=drained["failed"],
        markers=[str(m) for m in seen_markers],
    )
    log.info(
        "intake_run_finished",
        root=str(root),
        swept=result.swept,
        skipped=result.skipped,
        conflicts=result.conflicts,
        redacted=result.redacted,
        failed=result.failed,
    )
    return result


def _drain_only(limit, root, shards, of) -> RunResult:
    # Only ever rows a completed sweep recorded, so settled by definition.
    drained = intake_worker.drain(
        limit=limit, check_settled=False, shards=shards, of=of, root=root
    )
    if not drained["claimed"]:
        return RunResult(IDLE, "nothing new has arrived")
    return RunResult(
        RAN,
        "finished what an earlier run left queued",
        redacted=drained["done"],
        failed=drained["failed"],
    )


def watch(
    root: Optional[Path] = None,
    every_seconds: float = 60,
    quiet_seconds: Optional[float] = None,
    stop=None,
    shards: Optional[List[int]] = None,
    of: int = 1,
) -> None:
    """Check every `every_seconds`, for as long as the process runs.

    The alternative to a scheduled Job for somewhere that can keep a process
    alive. `stop` is a threading.Event, for tests and clean shutdown.
    """
    import threading

    stop = stop or threading.Event()
    log.info("intake_watch_started", every_seconds=every_seconds)
    while not stop.is_set():
        try:
            result = run_once(root, quiet_seconds, shards=shards, of=of)
            if result.outcome == RAN:
                log.info("intake_watch_ran", **{
                    k: v for k, v in result.__dict__.items() if k != "markers"
                })
        except Exception as exc:  # pragma: no cover - the loop must survive
            log.exception("intake_watch_error", error=str(exc))
        stop.wait(every_seconds)
