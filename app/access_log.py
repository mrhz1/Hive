import os
import queue
import threading
import uuid
from datetime import datetime, timezone
from typing import List, Optional

import structlog

from app.db import execute, hive_cursor
from app.logging_setup import get_logger

log = get_logger(__name__)

COLUMNS = (
    "id",
    "occurred_at",
    "action",
    "outcome",
    "actor_id",
    "actor_username",
    "actor_role",
    "source_ip",
    "user_agent",
    "request_id",
    "method",
    "path",
    "resource_type",
    "resource_id",
    "patient_id",
    "application_id",
    "identified",
    "record_count",
    "byte_count",
    "detail",
)

PARTITION_COLUMN = "event_date"

_COLS = ", ".join(f"`{c}`" for c in COLUMNS)

READ = "read"
DOWNLOAD = "download"
EXPORT = "export"
DENIED = "denied"
AUTH_FAILURE = "auth_failure"
INTEGRITY = "integrity"

SUCCESS = "success"
FAILURE = "failure"

FLUSH_SECONDS = float(os.environ.get("ACCESS_LOG_FLUSH_SECONDS", "5"))

MAX_BATCH = int(os.environ.get("ACCESS_LOG_MAX_BATCH", "200"))

MAX_QUEUED = int(os.environ.get("ACCESS_LOG_MAX_QUEUED", "10000"))

ENABLED = (os.environ.get("ACCESS_LOG_ENABLED", "true") or "").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)

_queue: "queue.Queue[dict]" = queue.Queue(maxsize=MAX_QUEUED)
_thread: Optional[threading.Thread] = None
_thread_lock = threading.Lock()
_stop = threading.Event()

_dropped = 0


def _context() -> dict:
    return structlog.contextvars.get_contextvars()


def record_access(
    action: str,
    *,
    outcome: str = SUCCESS,
    actor=None,
    actor_username: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    patient_id: Optional[str] = None,
    application_id: Optional[str] = None,
    identified: Optional[bool] = None,
    record_count: Optional[int] = None,
    byte_count: Optional[int] = None,
    detail: Optional[str] = None,
) -> None:
    context = _context()

    event = {
        "id": str(uuid.uuid4()),
        "occurred_at": datetime.now(timezone.utc),
        "action": action,
        "outcome": outcome,
        "actor_id": getattr(actor, "id", None),
        "actor_username": getattr(actor, "username", None) or actor_username,
        "actor_role": getattr(actor, "role_name", None),
        "source_ip": context.get("source_ip"),
        "user_agent": context.get("user_agent"),
        "request_id": context.get("request_id"),
        "method": context.get("method"),
        "path": context.get("path"),
        "resource_type": resource_type,
        "resource_id": resource_id,
        "patient_id": patient_id,
        "application_id": application_id,
        "identified": identified,
        "record_count": record_count,
        "byte_count": byte_count,
        "detail": detail,
    }

    log.info(
        f"access_{action}",
        outcome=outcome,
        actor_id=event["actor_id"],
        resource_type=resource_type,
        resource_id=resource_id,
        patient_id=patient_id,
        identified=identified,
        record_count=record_count,
    )

    if not ENABLED:
        return

    _enqueue(event)


def _enqueue(event: dict) -> None:
    global _dropped

    try:
        _queue.put_nowait(event)
    except queue.Full:
        _dropped += 1
        log.error("access_log_dropped", queued=_queue.qsize(), dropped=_dropped)
        return

    _ensure_writer()




def _ensure_writer() -> None:
    global _thread

    with _thread_lock:
        if _thread is None or not _thread.is_alive():
            _stop.clear()
            _thread = threading.Thread(
                target=_loop, name="access-log-writer", daemon=True
            )
            _thread.start()
            log.info("access_log_writer_started")


def _drain(limit: int) -> List[dict]:
    batch: List[dict] = []
    while len(batch) < limit:
        try:
            batch.append(_queue.get_nowait())
        except queue.Empty:
            break
    return batch


def _value_row(event: dict) -> tuple:
    return tuple(event[column] for column in COLUMNS)


def _write(batch: List[dict]) -> None:
    by_date: dict = {}
    for event in batch:
        day = event["occurred_at"].strftime("%Y-%m-%d")
        by_date.setdefault(day, []).append(event)

    with hive_cursor() as cursor:
        for day, events in by_date.items():
            placeholders = ", ".join(
                "(" + ", ".join("%s" for _ in COLUMNS) + ")" for _ in events
            )
            params: list = []
            for event in events:
                params.extend(_value_row(event))

            execute(
                cursor,
                f"INSERT INTO TABLE `access_logs` "
                f"PARTITION (`{PARTITION_COLUMN}` = %s) ({_COLS}) "
                f"VALUES {placeholders}",
                tuple([day] + params),
            )

    log.debug("access_log_flushed", events=len(batch), days=len(by_date))


def flush_once() -> int:
    batch = _drain(MAX_BATCH)
    if not batch:
        return 0

    try:
        _write(batch)
    except Exception as exc:
        log.error("access_log_write_failed", events=len(batch), error=str(exc))
        return 0

    return len(batch)


def _loop() -> None:
    while not _stop.is_set():
        _stop.wait(FLUSH_SECONDS)
        try:
            while flush_once() == MAX_BATCH:
                continue
        except Exception as exc:  # pragma: no cover - the thread must not die
            log.exception("access_log_writer_error", error=str(exc))

    log.info("access_log_writer_stopped")


def stop(timeout: float = 10.0) -> None:
    _stop.set()

    thread = _thread
    if thread is not None and thread.is_alive():
        thread.join(timeout=timeout)

    while flush_once():
        pass
