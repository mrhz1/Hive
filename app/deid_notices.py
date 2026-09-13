"""One email per application once its de-identification runs have settled.

A de-identification wave is a set of per-file runs with no record tying them
together, so "the batch is done" is read off the rows instead: every file the
user started is out of `queued`/`processing`. Whichever run finishes last is
the one that sends the notice.
"""

import hashlib
import json
import os
import time
from pathlib import Path
from typing import List, Optional, Sequence

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

IN_FLIGHT = ("queued", "processing")

NOTICE_SUBFOLDER = ".deid-notices"

# Two runs of the same application finishing in the same instant both see an
# idle table. The marker keeps the second one quiet, as long as it lands while
# the first notice is still this recent and describes the same outcome.
REPEAT_AFTER_SECONDS = float(os.environ.get("DEID_NOTICE_REPEAT_SECONDS", "120"))


def notice_path(application_id: str) -> Path:
    segment = storage.safe_path_segment(application_id)
    return storage.STORAGE_ROOT / NOTICE_SUBFOLDER / f"{segment}.json"


def _fingerprint(records: Sequence) -> str:
    digest = hashlib.sha256()
    for record in records:
        digest.update(f"{record.id}:{record.deid_status}\n".encode("utf-8"))
    return digest.hexdigest()


def _last_notice(path: Path) -> Optional[dict]:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        log.debug("deid_notice_marker_unreadable", path=str(path), error=str(exc))
        return None
    return state if isinstance(state, dict) else None


def _claim(application_id: str, fingerprint: str) -> bool:
    path = notice_path(application_id)
    previous = _last_notice(path)

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
    except OSError as exc:
        # Without the marker a duplicate is possible, but a missing notice is
        # the worse outcome -- carry on and send.
        log.warning(
            "deid_notice_marker_write_failed",
            application_id=application_id,
            error=str(exc),
        )

    return True


def summarise(application_id: str, records: Sequence) -> DeidBatchSummary:
    settled = sorted(
        (r for r in records if r.deid_status in ("done", "failed")),
        key=lambda r: r.created_at,
    )

    def names(status: str) -> List[str]:
        return [
            r.deidentified_file_name or r.sanitized_file_name
            for r in settled
            if r.deid_status == status
        ]

    deidentified = names("done")
    failed = names("failed")

    return DeidBatchSummary(
        application_id=application_id,
        total=len(settled),
        deidentified=len(deidentified),
        failed=len(failed),
        deidentified_names=deidentified,
        failed_names=failed,
    )


def notify_if_finished(application_id: str) -> bool:
    """Email the application's owner if no de-identification is still running."""

    if not application_id:
        return False

    try:
        with hive_cursor() as cursor:
            records = crud.list_files(cursor, application_id)
    except Exception as exc:
        log.error(
            "deid_notice_lookup_failed", application_id=application_id, error=str(exc)
        )
        return False

    waiting = [r.id for r in records if r.deid_status in IN_FLIGHT]
    if waiting:
        log.info(
            "deid_notice_deferred",
            application_id=application_id,
            still_running=len(waiting),
        )
        return False

    summary = summarise(application_id, records)
    if not summary.total:
        return False

    if not _claim(application_id, _fingerprint(records)):
        return False

    try:
        with hive_cursor() as cursor:
            recipients = upload_recipients(cursor, application_id)
            source_folder = source_folder_for(cursor, application_id)
    except Exception as exc:
        log.error(
            "deid_notice_lookup_failed", application_id=application_id, error=str(exc)
        )
        return False

    if not recipients:
        return False

    try:
        sent = notify_deid_finished(recipients, summary, source_folder)
    except Exception as exc:  # pragma: no cover - mailer already swallows
        log.error(
            "deid_notice_failed", application_id=application_id, error=str(exc)
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
