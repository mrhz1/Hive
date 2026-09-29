import hashlib
import json
import os
import time
from pathlib import Path
from typing import Optional

from app import storage
from app.crud import patient_application_files as crud
from app.db import hive_cursor
from app.logging_setup import get_logger
from app.notifications import (
    notify_deid_finished,
    source_folder_for,
    upload_recipients,
)
from app.schemas import DeidBatchSummary

log = get_logger(__name__)

RUNNING_STATUSES = ("queued", "processing")

NOTICE_SUBFOLDER = ".deid-notices"

REPEAT_AFTER_SECONDS = float(os.environ.get("DEID_NOTICE_REPEAT_SECONDS", "120"))


def notice_path(application_id: str) -> Path:
    segment = storage.safe_path_segment(application_id)
    return storage.STORAGE_ROOT / NOTICE_SUBFOLDER / f"{segment}.json"


def _fingerprint(records: list) -> str:
    digest = hashlib.sha256()
    for record in records:
        digest.update(f"{record.id}:{record.deid_status}\n".encode("utf-8"))
    return digest.hexdigest()


def _read_notice(path: Path) -> Optional[dict]:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        log.debug("deid_notice_marker_unreadable", path=str(path), error=str(e))
        return None
    return state if isinstance(state, dict) else None


def _should_send(application_id: str, fingerprint: str) -> bool:
    path = notice_path(application_id)
    previous = _read_notice(path)

    if previous and previous.get("fingerprint") == fingerprint:
        age = time.time() - float(previous.get("sent_at") or 0.0)
        if age < REPEAT_AFTER_SECONDS:
            log.info(
                "deid_notice_already_sent",
                application_id=application_id,
                seconds_ago=round(age, 1),
            )
            return False

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"fingerprint": fingerprint, "sent_at": time.time()}),
            encoding="utf-8",
        )
    except OSError as e:
        log.warning(
            "deid_notice_marker_write_failed",
            application_id=application_id,
            error=str(e),
        )

    return True


def summarize(application_id: str, records: list) -> DeidBatchSummary:
    settled = sorted(
        (r for r in records if r.deid_status in ("done", "failed")),
        key=lambda r: r.created_at,
    )

    deidentified = []
    failed = []
    for r in settled:
        name = r.deidentified_file_name or r.sanitized_file_name
        if r.deid_status == "done":
            deidentified.append(name)
        else:
            failed.append(name)

    return DeidBatchSummary(
        application_id=application_id,
        total=len(settled),
        deidentified=len(deidentified),
        failed=len(failed),
        deidentified_names=deidentified,
        failed_names=failed,
    )


def notify_if_finished(application_id: str) -> bool:
    if not application_id:
        return False

    try:
        with hive_cursor() as cursor:
            records = crud.list_files(cursor, application_id)
    except Exception as e:
        log.error(
            "deid_notice_lookup_failed", application_id=application_id, error=str(e)
        )
        return False

    waiting = [r.id for r in records if r.deid_status in RUNNING_STATUSES]
    if waiting:
        log.info(
            "deid_notice_deferred",
            application_id=application_id,
            still_running=len(waiting),
        )
        return False

    summary = summarize(application_id, records)
    if not summary.total:
        return False

    if not _should_send(application_id, _fingerprint(records)):
        return False

    try:
        with hive_cursor() as cursor:
            recipients = upload_recipients(cursor, application_id)
            source_folder = source_folder_for(cursor, application_id)
    except Exception as e:
        log.error(
            "deid_notice_lookup_failed", application_id=application_id, error=str(e)
        )
        return False

    if not recipients:
        return False

    try:
        sent = notify_deid_finished(recipients, summary, source_folder)
    except Exception as e:
        log.error(
            "deid_notice_failed", application_id=application_id, error=str(e)
        )
        return False

    log.info(
        "deid_notice_sent",
        application_id=application_id,
        deidentified=summary.deidentified,
        failed=summary.failed,
        delivered=sent,
    )
    return sent
