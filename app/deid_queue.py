"""Serialised dispatch of de-identification Job runs.

Cloudera will not run two runs of one Job at once. Ask it to anyway and
it answers `400 job run for job <id> already active, code 9`, records a
**Skipped** entry in the run history, and -- before this module existed
-- the API turned that refusal into `deid_status='failed'` on a file
nobody had even looked at yet.

The fix is to stop asking. Clicking De-identify marks the row `queued`
and wakes the single dispatcher thread that lives here; the thread starts
one run, waits for it to finish, and only then starts the next. Because a
second run is never *requested* while one is active, there is no refusal
to mishandle: no 400, no Skipped entry, no spurious failure.

That also removes the need for a Job schedule. Scheduling was the other
way to drain the queue, but CML's scheduler only offers "every minute" or
"N minutes past the hour", and this work has no characteristic duration
-- a one-page PDF finishes in under a minute and a hundred-page one takes
far longer than any fixed interval.

## Ordering

Oldest `queued` row first, so the queue is FIFO by the moment the user
clicked. Files still in `pending` are ignored: that is the state every
upload starts in, and it carries no signal that anybody asked for it.

## What this does not do

One dispatcher per API process. Two API replicas mean two dispatchers and
the refusal comes back -- run this API single-replica, which is also what
the Job's own single-run-at-a-time constraint implies. `DEID_BACKEND` is
still the switch: `inline` never reaches this module.
"""
import os
import threading
import time

from app.cloudera import (
    ClouderaCapacityError,
    ClouderaError,
    get_job_run_status,
    is_terminal_run_status,
    start_deid_job_run,
)
from app.crud import patient_application_files as crud
from app.db import hive_cursor
from app.logging_setup import get_logger

log = get_logger(__name__)

# How often to ask whether the active run has finished. The answer costs
# one small API call plus one Hive read, and a few seconds of latency at
# the end of a multi-minute run is not worth optimising away.
POLL_SECONDS = float(os.environ.get("DEID_DISPATCH_POLL_SECONDS", "10"))

# How long to sit idle before re-reading the table anyway. The thread is
# poked on every click, so this only catches rows that appeared without
# one -- a row left `queued` by a previous process, say.
IDLE_SECONDS = float(os.environ.get("DEID_DISPATCH_IDLE_SECONDS", "60"))

# Give up waiting on a single run after this long. Generous: a large
# scanned PDF legitimately takes a long time, and giving up early is
# worse than waiting, because it lets a second run be requested while the
# first is still going -- exactly the Skipped entry this module exists to
# prevent.
MAX_RUN_SECONDS = float(os.environ.get("DEID_DISPATCH_MAX_RUN_SECONDS", "10800"))

# Backoff after a dispatch error, so a misconfigured job id cannot spin
# this thread against the control plane.
ERROR_BACKOFF_SECONDS = float(os.environ.get("DEID_DISPATCH_BACKOFF_SECONDS", "60"))

_TERMINAL_ROW_STATES = ("done", "failed")

_thread = None
_thread_lock = threading.Lock()
_wake = threading.Event()
_stop = threading.Event()


def request_dispatch() -> None:
    """Ensure the dispatcher is running and wake it. Returns immediately.

    Safe to call from a FastAPI BackgroundTask on every click: the work
    happens on the dispatcher thread, so the request's threadpool worker
    is not held for the length of a run.
    """
    global _thread

    with _thread_lock:
        if _thread is None or not _thread.is_alive():
            _stop.clear()
            _thread = threading.Thread(
                target=_loop, name="deid-dispatch", daemon=True
            )
            _thread.start()
            log.info("deid_dispatcher_started")

    _wake.set()


def stop() -> None:
    """Ask the dispatcher to finish the current wait and exit (tests, shutdown)."""
    _stop.set()
    _wake.set()


def next_queued():
    """Oldest row in `queued`, or None.

    Read fresh every time rather than held as a list: a run takes minutes,
    and the table can change underneath a stale snapshot.
    """
    with hive_cursor() as cursor:
        every = crud.list_files(cursor)

    waiting = [f for f in every if f.deid_status == "queued"]
    if not waiting:
        return None
    return min(waiting, key=lambda f: f.created_at)


def _row_status(file_id: str) -> str:
    with hive_cursor() as cursor:
        record = crud.get_file(cursor, file_id)
    return record.deid_status if record else ""


def _wait_for_run(run_id: str, file_id: str) -> bool:
    """Block until the run is over. True if it ended, False on timeout.

    Two independent signals, because either can be missed. The row going
    `done`/`failed` means the worker finished and is the one that matters;
    the run's own status catches a run that died without ever writing the
    row. An unreadable run status counts as still-running, so a blip in
    the control plane makes this wait rather than race ahead.
    """
    deadline = time.monotonic() + MAX_RUN_SECONDS

    while time.monotonic() < deadline:
        if _stop.wait(POLL_SECONDS):
            return False

        status = _row_status(file_id)
        if status in _TERMINAL_ROW_STATES:
            log.info("deid_run_finished", file_id=file_id, run_id=run_id, row=status)
            return True

        run_status = get_job_run_status(run_id)
        if is_terminal_run_status(run_status):
            # The run is over but the row is not final -- the worker died
            # mid-file, or never claimed it. Say so plainly; the row is
            # left alone so the next pass can retry it.
            log.warning(
                "deid_run_ended_without_result",
                file_id=file_id,
                run_id=run_id,
                run_status=run_status,
                row=status,
            )
            return True

    log.error(
        "deid_run_wait_timeout",
        file_id=file_id,
        run_id=run_id,
        waited_seconds=MAX_RUN_SECONDS,
    )
    return False


def _dispatch_one(record) -> None:
    """Start one run and wait it out. Never marks the row failed.

    A dispatch problem is a property of the control plane, not of the
    file: leaving the row `queued` means the next pass retries it, where
    marking it `failed` would need a human to re-click something that was
    never wrong.
    """
    try:
        run_id = start_deid_job_run(environment={"DEID_FILE_ID": record.id})
    except ClouderaCapacityError as exc:
        # Busy or out of quota. Should be rare now that this thread is
        # the only caller, but a Job run started by hand still collides.
        log.warning("deid_dispatch_deferred", file_id=record.id, error=str(exc))
        _stop.wait(POLL_SECONDS)
        return
    except ClouderaError as exc:
        log.error("deid_dispatch_failed", file_id=record.id, error=str(exc))
        _stop.wait(ERROR_BACKOFF_SECONDS)
        return

    log.info("deid_run_dispatched", file_id=record.id, run_id=run_id)
    _wait_for_run(run_id, record.id)


def drain_once() -> bool:
    """Dispatch at most one file. True if there was one to dispatch.

    Split out from the loop so it can be driven directly in a test
    without a thread.
    """
    record = next_queued()
    if record is None:
        return False

    _dispatch_one(record)
    return True


def _loop() -> None:
    while not _stop.is_set():
        try:
            worked = drain_once()
        except Exception as exc:  # pragma: no cover - the thread must not die
            log.exception("deid_dispatcher_error", error=str(exc))
            _stop.wait(ERROR_BACKOFF_SECONDS)
            continue

        if not worked:
            # Idle: wait to be poked, and re-check periodically anyway so
            # a row that appeared without a click is not stranded.
            _wake.wait(IDLE_SECONDS)
            _wake.clear()

    log.info("deid_dispatcher_stopped")
