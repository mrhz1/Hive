"""Serialised dispatch of de-identification Job runs."""
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

# How soon after starting a run to ask whether it is over. Short, because
# a one-page file really can be finished by then.
POLL_SECONDS = float(os.environ.get("DEID_DISPATCH_POLL_SECONDS", "10"))

# ...and how far apart those questions are allowed to get. A run is OCR
# over a document: minutes, sometimes tens of them. Asking every ten
# seconds for the whole of one is hundreds of calls to the control plane
# to be told the same thing, which is what made the API look besieged.
# Opening the interval out to a minute costs a handful of calls an hour
# and still notices a finished run promptly.
MAX_POLL_SECONDS = float(os.environ.get("DEID_DISPATCH_MAX_POLL_SECONDS", "60"))

POLL_BACKOFF = float(os.environ.get("DEID_DISPATCH_POLL_BACKOFF", "1.5"))

IDLE_SECONDS = float(os.environ.get("DEID_DISPATCH_IDLE_SECONDS", "60"))

MAX_RUN_SECONDS = float(os.environ.get("DEID_DISPATCH_MAX_RUN_SECONDS", "10800"))

ERROR_BACKOFF_SECONDS = float(os.environ.get("DEID_DISPATCH_BACKOFF_SECONDS", "60"))

_TERMINAL_ROW_STATES = ("done", "failed")

UNREADABLE_POLLS_BEFORE_ROW = int(
    os.environ.get("DEID_DISPATCH_UNREADABLE_POLLS", "6")
)

_thread = None
_thread_lock = threading.Lock()
_wake = threading.Event()
_stop = threading.Event()

# Consecutive refusals for want of capacity. Kept across dispatch attempts
# because that is the thing being backed off: one busy answer is normal,
# twenty in a row means the Job has been occupied for a while and asking
# again every ten seconds only adds a Skipped run to somebody's history.
_deferrals = 0

# How many times a file may be dispatched to a run that ends without
# touching it, before it is called failed rather than tried again.
MAX_ATTEMPTS = int(os.environ.get("DEID_DISPATCH_MAX_ATTEMPTS", "2"))

# file id -> dispatches that came back with the row untouched.
_attempts: dict = {}


def _next_poll(interval: float) -> float:
    """The next wait in a run of polls, opening out towards the cap."""
    return min(interval * POLL_BACKOFF, MAX_POLL_SECONDS)


def _deferral_wait() -> float:
    """How long to leave a busy control plane alone, by how busy it has been."""
    return min(POLL_SECONDS * (POLL_BACKOFF**_deferrals), MAX_POLL_SECONDS)


def request_dispatch() -> None:
    """Ensure the dispatcher is running and wake it."""
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
    """Oldest row in `queued`, or None."""
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
    """Block until the *run* is over.

    The gap between questions grows: quick at first, because a small file
    may already be done, then out to `MAX_POLL_SECONDS` for the long
    middle of a run where the answer is not going to change for minutes.
    """
    deadline = time.monotonic() + MAX_RUN_SECONDS
    unreadable = 0
    interval = POLL_SECONDS

    while time.monotonic() < deadline:
        if _stop.wait(interval):
            return False
        interval = _next_poll(interval)

        run_status = get_job_run_status(run_id)

        if is_terminal_run_status(run_status):
            log.info(
                "deid_run_finished",
                file_id=file_id,
                run_id=run_id,
                run_status=run_status,
                row=_row_status(file_id),
            )
            return True

        if run_status:
            unreadable = 0
            continue

        unreadable += 1
        if unreadable >= UNREADABLE_POLLS_BEFORE_ROW:
            row = _row_status(file_id)
            if row in _TERMINAL_ROW_STATES:
                log.warning(
                    "deid_run_status_unavailable_row_final",
                    file_id=file_id,
                    run_id=run_id,
                    row=row,
                )
                return True

    log.error(
        "deid_run_wait_timeout",
        file_id=file_id,
        run_id=run_id,
        waited_seconds=MAX_RUN_SECONDS,
    )
    return False


def _fail_row(file_id: str, detail: str) -> None:
    """Mark a file failed, so it stops being handed round the queue."""
    from app.crud import patient_application_files as files_crud
    from app.schemas import PatientApplicationFileUpdate

    try:
        with hive_cursor() as cursor:
            files_crud.update_file(
                cursor, file_id, PatientApplicationFileUpdate(deid_status="failed")
            )
    except Exception as exc:  # pragma: no cover - last-resort logging
        log.error("deid_fail_write_failed", file_id=file_id, error=str(exc))
        return

    log.error("deid_abandoned", file_id=file_id, detail=detail)


def _dispatch_one(record) -> None:
    """Start one run and wait it out."""
    global _deferrals

    try:
        run_id = start_deid_job_run(environment={"DEID_FILE_ID": record.id})
    except ClouderaCapacityError as exc:
        # The row stays queued and comes back round. Waiting longer each
        # time is what stops a Job that is busy for half an hour being
        # asked a hundred and eighty times whether it is free yet.
        wait = _deferral_wait()
        _deferrals += 1
        log.warning(
            "deid_dispatch_deferred",
            file_id=record.id,
            error=str(exc),
            retry_in_seconds=round(wait, 1),
            consecutive=_deferrals,
        )
        _stop.wait(wait)
        return
    except ClouderaError as exc:
        log.error("deid_dispatch_failed", file_id=record.id, error=str(exc))
        _stop.wait(ERROR_BACKOFF_SECONDS)
        return

    _deferrals = 0
    log.info("deid_run_dispatched", file_id=record.id, run_id=run_id)
    _wait_for_run(run_id, record.id)

    # The run is over. If the row is still queued, it ended without ever
    # claiming this file -- which is what a run killed part way through
    # looks like from here, and OCR being killed for memory is the usual
    # reason. Left alone the file is picked up again on the next pass,
    # dies the same way, and the queue turns into a loop that never
    # empties. Two goes, then it is marked failed and somebody is told.
    if _row_status(record.id) != "queued":
        _attempts.pop(record.id, None)
        return

    attempts = _attempts.get(record.id, 0) + 1
    _attempts[record.id] = attempts

    if attempts >= MAX_ATTEMPTS:
        _attempts.pop(record.id, None)
        _fail_row(
            record.id,
            f"the run finished without processing this file, {attempts} times over",
        )
    else:
        log.warning(
            "deid_run_left_row_queued", file_id=record.id, attempts=attempts
        )


def drain_once() -> bool:
    """Dispatch at most one file."""
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
            _wake.wait(IDLE_SECONDS)
            _wake.clear()

    log.info("deid_dispatcher_stopped")
