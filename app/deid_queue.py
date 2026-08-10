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

POLL_SECONDS = float(os.environ.get("DEID_DISPATCH_POLL_SECONDS", "10"))

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
    """Block until the *run* is over."""
    deadline = time.monotonic() + MAX_RUN_SECONDS
    unreadable = 0

    while time.monotonic() < deadline:
        if _stop.wait(POLL_SECONDS):
            return False

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


def _dispatch_one(record) -> None:
    """Start one run and wait it out."""
    try:
        run_id = start_deid_job_run(environment={"DEID_FILE_ID": record.id})
    except ClouderaCapacityError as exc:
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
