import os
from pathlib import Path
from typing import Optional

import structlog

from app.crud import patient_application_files as files_crud
from app.crud import patient_applications as applications_crud
from app.db import hive_cursor
from app.deid import remove_deid_artifacts
from app.logging_setup import get_logger
from app.stamp import StampError, stamp_pdf
from app import intake
from app.storage import (
    delete_file as remove_from_disk,
    move_into,
    prune_empty_dirs,
    resolve_stored_path,
    submitted_dir_for,
)

log = get_logger(__name__)

STAMPABLE = ("pdf",)

ORIGINAL = "original"
DEIDENTIFIED = "de_identified"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def keep_original() -> bool:
    """Whether the identified original outlives submission.

    Read per call rather than at import, so a deployment can change it
    without a restart -- and so a test can set it for one submission.
    """
    return _env_bool("DEID_KEEP_ORIGINAL", True)


def _drop_sidecars(directory: Path, stem: str, keep: Path) -> None:
    """Remove the run's text and report that sat beside the redacted copy.

    An intake run writes all three into the mirror with one stem. Once the
    copy has moved, the other two point at nothing -- and the report is the
    one artifact that can hold identifiers in the clear.
    """
    try:
        siblings = [p for p in directory.iterdir() if p.is_file()]
    except OSError:
        return
    for path in siblings:
        if path.name.startswith(stem) and path != keep:
            remove_from_disk(str(path))


def process_one(record, patient_id: str) -> bool:
    """File one document's two copies under the patient's submitted folder.

        <SUBMITTED_DIR>/<CODE>/de_identified/<redacted name>
        <SUBMITTED_DIR>/<CODE>/original/<original name>

    Both move, and the row is pointed at both in one write, so there is no
    moment at which it names a file that has already gone.
    """
    if not record.de_identified_file_path:
        return False

    extension = (record.file_extension or "").lower()

    try:
        staged = resolve_stored_path(record.de_identified_file_path)
    except Exception as exc:
        log.error(
            "submission_output_unresolvable",
            file_id=record.id,
            path=record.de_identified_file_path,
            error=str(exc),
        )
        return False

    if not staged.is_file():
        log.error("submission_output_missing", file_id=record.id, path=str(staged))
        return False

    original = None
    if record.file_path:
        try:
            original = resolve_stored_path(record.file_path)
        except Exception as exc:  # pragma: no cover - logged, filing carries on
            log.warning("submission_original_unresolvable", file_id=record.id, error=str(exc))

    if extension in STAMPABLE:
        try:
            stamp_pdf(staged, patient_id)
        except StampError as exc:
            log.error("submission_stamp_failed", file_id=record.id, error=str(exc))

    folder = submitted_dir_for(patient_id)
    staged_dir, staged_stem = staged.parent, staged.stem

    try:
        final = move_into(staged, folder / DEIDENTIFIED)
    except Exception as exc:
        log.error("submission_file_failed", file_id=record.id, error=str(exc))
        return False

    _drop_sidecars(staged_dir, staged_stem, final)

    # A manually attached redacted copy has no separate original: the row's
    # two paths name the same file, and it has just moved.
    same_file = original is not None and _resolved(original) == _resolved(staged)

    kept = None
    if original is not None and not same_file and original.is_file():
        # An uploaded file's run left its sidecars in `<original>/deidentified/`.
        remove_deid_artifacts(record.file_path, record.deidentified_file_name or "")

        if keep_original():
            kept = move_into(original, folder / ORIGINAL)
        else:
            remove_from_disk(record.file_path)
            log.info("submission_original_removed", file_id=record.id)
    elif same_file:
        kept = final

    try:
        with hive_cursor() as cursor:
            # A discarded original keeps its old path: the column is
            # required, and anything that reads it checks the disk first
            # (has_original on the Rejections page) rather than trusting it.
            files_crud.set_paths(
                cursor, record.id, str(kept) if kept else record.file_path, str(final)
            )
            intake.mark_submitted(cursor, record.id)
    except Exception as exc:  # pragma: no cover - last-resort logging
        log.error("submission_path_write_failed", file_id=record.id, error=str(exc))

    for emptied in (staged_dir, original.parent if original else None):
        if emptied is not None:
            prune_empty_dirs(emptied)

    log.info(
        "submission_filed",
        file_id=record.id,
        patient_id=patient_id,
        deidentified=str(final),
        original=str(kept) if kept else None,
    )
    return True


def _resolved(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:  # pragma: no cover - unreadable path
        return path


def finalise_submission(
    application_id: str, request_id: Optional[str] = None
) -> None:
    if request_id:
        structlog.contextvars.bind_contextvars(
            request_id=request_id, background_task="finalise_submission"
        )

    try:
        with hive_cursor() as cursor:
            application = applications_crud.get_application(cursor, application_id)
            records = files_crud.list_files(cursor, application_id)
    except Exception as exc:
        log.error(
            "submission_lookup_failed", application_id=application_id, error=str(exc)
        )
        return

    patient_id = getattr(application, "patient_id", "") if application else ""
    if not patient_id:
        log.error("submission_without_patient", application_id=application_id)
        return

    ready = [r for r in records if r.deid_status == "done" and r.de_identified_file_path]

    if not ready:
        log.info(
            "submission_nothing_to_file",
            application_id=application_id,
            files=len(records),
        )
        return

    filed = sum(1 for record in ready if process_one(record, patient_id))

    log.info(
        "submission_finalised",
        application_id=application_id,
        patient_id=patient_id,
        filed=filed,
        skipped=len(ready) - filed,
    )
