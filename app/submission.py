"""What happens after an application is submitted."""
from pathlib import Path
from typing import Optional

import structlog

from app.crud import patient_application_files as files_crud
from app.crud import patient_applications as applications_crud
from app.db import hive_cursor
from app.deid import remove_deid_artifacts
from app.logging_setup import get_logger
from app.schemas import PatientApplicationFileUpdate
from app.stamp import StampError, stamp_pdf
from app.storage import (
    delete_file as remove_from_disk,
    file_deidentified_output,
    prune_empty_dirs,
    resolve_stored_path,
)

log = get_logger(__name__)

STAMPABLE = ("pdf",)


def _set_path(file_id: str, path: str) -> None:
    try:
        with hive_cursor() as cursor:
            files_crud.update_file(
                cursor,
                file_id,
                PatientApplicationFileUpdate(de_identified_file_path=path),
            )
    except Exception as exc:  # pragma: no cover - last-resort logging
        log.error("deid_path_write_failed", file_id=file_id, error=str(exc))


def process_one(record, patient_id: str) -> bool:
    """Stamp and file one de-identified output. True if it was filed."""
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
        log.error(
            "submission_output_missing", file_id=record.id, path=str(staged)
        )
        return False

    if extension in STAMPABLE:
        try:
            stamp_pdf(staged, patient_id)
        except StampError as exc:
            log.error("submission_stamp_failed", file_id=record.id, error=str(exc))

    try:
        final = file_deidentified_output(str(staged), extension, patient_id)
    except Exception as exc:
        log.error("submission_file_failed", file_id=record.id, error=str(exc))
        return False

    if str(final) != record.de_identified_file_path:
        _set_path(record.id, str(final))

    _discard_original(record, final)
    return True


def _resolved(path: Path) -> Path:
    """Best-effort resolve; an unresolvable path is still worth comparing."""
    try:
        return path.resolve()
    except OSError:  # pragma: no cover - unreadable path
        return path


def _discard_original(record, final: Path) -> None:
    """Delete the identified copy, now that the redacted one is filed.

    Only ever after the redacted copy has been moved into place: the
    original is the thing that cannot be reconstructed, so it goes last
    and only once there is something to replace it. Submitting is the
    point at which the application no longer needs it, and keeping
    identified documents past that point is the risk the whole
    de-identification pass exists to remove.
    """
    if not record.file_path:
        return

    try:
        original = resolve_stored_path(record.file_path)
    except Exception as exc:  # pragma: no cover - cleanup is best effort
        log.warning(
            "submission_original_not_removed", file_id=record.id, error=str(exc)
        )
        return

    # Both resolved before comparing: `final` is built from a configured
    # directory, and a symlink anywhere in it would otherwise make the
    # same file look like two different ones -- which is the comparison
    # this whole branch turns on.
    if original == _resolved(final):
        # A document attached already redacted: there is no original
        # behind it, so both paths on the row name the same file. This
        # used to delete it -- the one copy in existence -- moments
        # after filing it, and the submitted application came out the
        # other side with nothing under the patient's folder.
        log.info("submission_original_is_the_output", file_id=record.id)
        return

    # Before the original goes, while its name is still the way to find
    # them: the run also wrote the text it read out of the document and
    # a report of what it redacted, in a folder beside it. Neither is
    # recorded anywhere, and the text is the document in the clear --
    # exactly what discarding the original is meant to be the end of.
    remove_deid_artifacts(record.file_path)

    try:
        remove_from_disk(record.file_path)
    except Exception as exc:  # pragma: no cover - cleanup is best effort
        log.warning(
            "submission_original_not_removed", file_id=record.id, error=str(exc)
        )
        return

    log.info("submission_original_removed", file_id=record.id)

    # The upload's own folder, once the last document has left it. A
    # folder still holding something -- a document that was never
    # de-identified, so was never filed -- is left alone.
    prune_empty_dirs(original.parent)


def finalise_submission(
    application_id: str, request_id: Optional[str] = None
) -> None:
    """Stamp and file every de-identified output on this application."""
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
