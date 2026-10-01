"""Deleting a rejected application's or file's documents, keeping the record.

The bytes go -- original, de-identified copy, its sidecar, any de-
identification artifacts and the extracted metadata -- but the rows stay,
marked deleted with the reason, so there is a record of what was removed and
why. Who and when are in the audit log. Nothing on a deleted row can be
opened or changed afterwards.

Only the files of the application being deleted are touched: every file
belongs to one application, so a patient's other applications keep theirs.
The patient's excluded and failed De-Identifier files belong to no
application, so they are removed only when the patient has no draft left that
they might still be meant for.
"""

from pathlib import Path
from typing import Dict, List

from app import intake
from app.crud import file_metadata as metadata_crud
from app.crud import patient_application_files as files_crud
from app.crud import patient_applications as applications_crud
from app.deid import remove_deid_artifacts
from app.errors import ValidationError
from app.logging_setup import get_logger
from app.schemas import PatientApplicationFileUpdate, PatientApplicationUpdate
from app.storage import delete_file as remove_from_disk, prune_empty_dirs, prune_stored_folders

log = get_logger(__name__)

DELETED = "deleted"
OPEN_STATUSES = ("draft",)


def is_deleted_file(record) -> bool:
    return record.review_status == DELETED or record.deid_status == DELETED


def refuse_if_deleted(record) -> None:
    if is_deleted_file(record):
        raise ValidationError(
            f"'{record.original_file_name}' was deleted"
            + (f": {record.review_note}" if record.review_note else "")
            + ". It can no longer be opened or changed."
        )


def _remove(stored) -> None:
    if stored:
        remove_from_disk(stored)


def purge_file(cursor, record, reason: str):
    """Remove one file's documents from disk and mark its row deleted."""
    try:
        remove_deid_artifacts(record.file_path, record.deidentified_file_name or "")
    except Exception as exc:
        log.warning("purge_artifacts_failed", file_id=record.id, error=str(exc))

    _remove(record.file_path)
    if record.de_identified_file_path:
        _remove(record.de_identified_file_path)
        _remove(record.de_identified_file_path + intake.SIDECAR_SUFFIX)
    prune_stored_folders(record.file_path, record.de_identified_file_path)

    metadata_crud.delete_metadata_for_files(cursor, [record.id])

    updated = files_crud.update_file(
        cursor,
        record.id,
        PatientApplicationFileUpdate(
            deid_status=DELETED,
            is_deidentified=False,
            de_identified_file_path="",
            review_status=DELETED,
            review_note=reason,
        ),
    )
    log.info("file_purged", file_id=record.id, application_id=record.application_id)
    return updated


def purge_rejected_file(cursor, file_id: str, reason: str):
    record = files_crud.get_file_or_404(cursor, file_id)
    refuse_if_deleted(record)
    if record.review_status != "rejected":
        raise ValidationError("Only a rejected file can be deleted from Rejections")
    return purge_file(cursor, record, _reason(reason))


def _reason(reason) -> str:
    text = (reason or "").strip()
    if not text:
        raise ValidationError("A reason is required to delete documents")
    return text


def _purge_problem_files(code: str) -> Dict[str, int]:
    removed = {}
    for kind in ("attention", "failed"):
        root = intake.problem_root(kind)
        count = 0
        for item in intake.filter_by_code(intake.list_problem_files(kind), code):
            try:
                path = intake.safe_child(root, item["path"])
            except ValueError:
                continue
            path.unlink(missing_ok=True)
            Path(str(path) + intake.REASON_SUFFIX).unlink(missing_ok=True)
            prune_empty_dirs(path.parent)
            count += 1
        removed[kind] = count
    return removed


def purge_rejected_application(cursor, application_id: str, reason: str, actor_id: str):
    """Delete a rejected application's documents; keep it as a locked record.

    Returns (before, after, summary).
    """
    before = applications_crud.get_application_or_404(cursor, application_id)
    reason = _reason(reason)
    if before.status != "rejected":
        raise ValidationError(
            f"Only a rejected application can be deleted; this one is '{before.status}'"
        )

    records = files_crud.list_files(cursor, application_id)
    purged: List[str] = []
    for record in records:
        if is_deleted_file(record):
            continue
        purge_file(cursor, record, reason)
        purged.append(record.id)

    after = applications_crud.update_application(
        cursor,
        application_id,
        PatientApplicationUpdate(status=DELETED, status_reason=reason),
        actor_id=actor_id,
    )

    code = before.patient_id
    still_open = [
        a
        for status in OPEN_STATUSES
        for a in applications_crud.list_applications(cursor, code, status=status)
        if a.id != application_id
    ]
    if still_open:
        problems = {"attention": 0, "failed": 0, "kept_for": [a.id for a in still_open]}
    else:
        problems = _purge_problem_files(code)

    summary = {
        "files_deleted": len(purged),
        "excluded_deleted": problems.get("attention", 0),
        "failed_deleted": problems.get("failed", 0),
        "excluded_and_failed_kept": bool(still_open),
    }
    log.info("application_purged", application_id=application_id, code=code, **summary)
    return before, after, summary
