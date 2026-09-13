import os
from typing import List, Optional, Sequence

from app.crud import patient_applications as applications_crud
from app.crud import users as users_crud
from app.logging_setup import get_logger
from app.mailer import send_email
from app.schemas import DeidBatchSummary, UploadJob, User

log = get_logger(__name__)


def application_link(application_id: str) -> Optional[str]:
    base = (os.environ.get("APP_BASE_URL") or "").strip().rstrip("/")
    if not application_id:
        return None
    if not base:
        log.warning(
            "application_link_unavailable",
            application_id=application_id,
            reason="APP_BASE_URL is not set",
        )
        return None
    return f"{base}/applications/{application_id}"


def _link_lines(application_id: str) -> List[str]:
    link = application_link(application_id)
    if link:
        return [f"Open the application: {link}"]
    return [f"Application: {application_id}"]


def _display_name(user: User) -> str:
    full = f"{user.first_name or ''} {user.last_name or ''}".strip()
    return full or user.username


def assignee_for_application(cursor, application_id: str) -> Optional[User]:
    application = applications_crud.get_application(cursor, application_id)
    assigned_to = getattr(application, "assigned_to_id", None)
    if not assigned_to:
        return None
    return users_crud.get_user(cursor, assigned_to)


def source_folder_for(cursor, application_id: str) -> Optional[str]:
    application = applications_crud.get_application(cursor, application_id)
    return getattr(application, "original_file_path", None)


def creator_of_application(cursor, application_id: str) -> Optional[User]:
    application = applications_crud.get_application(cursor, application_id)
    created_by = getattr(application, "created_by_id", None)
    if not created_by:
        return None
    return users_crud.get_user(cursor, created_by)


def upload_recipients(
    cursor, application_id: str, fallback_user_id: Optional[str] = None
) -> List[User]:
    assignee = assignee_for_application(cursor, application_id)
    if assignee is not None:
        return [assignee]

    creator = creator_of_application(cursor, application_id)
    if creator is not None:
        log.info(
            "upload_notice_unassigned",
            application_id=application_id,
            falling_back_to=creator.id,
            because="application creator",
        )
        return [creator]

    if fallback_user_id:
        actor = users_crud.get_user(cursor, fallback_user_id)
        if actor is not None:
            log.info(
                "upload_notice_unassigned",
                application_id=application_id,
                falling_back_to=actor.id,
                because="uploader",
            )
            return [actor]

    log.info("upload_notice_no_recipient", application_id=application_id)
    return []


def notify_assigned(assignee: User, application_id: str, assigned_by: User) -> bool:
    if not assignee or not assignee.email:
        log.info("assignment_notice_no_recipient", application_id=application_id)
        return False

    lines = [
        f"Hello {_display_name(assignee)},",
        "",
        f"{_display_name(assigned_by)} has assigned a patient application to you.",
        "",
    ]
    lines += _link_lines(application_id)
    lines += ["", "-- Hive"]

    return _send([assignee], "An application has been assigned to you", "\n".join(lines))


def _name_lines(names: Sequence[str], limit: int = 20) -> List[str]:
    lines = [f"  - {name}" for name in names[:limit]]
    if len(names) > limit:
        lines.append(f"  ... and {len(names) - limit} more")
    return lines


def _file_lines(job: UploadJob, status: str, limit: int = 20) -> List[str]:
    entries = [f for f in job.files if f.status == status]
    return _name_lines(
        [
            f"{entry.name}" + (f" ({entry.error})" if entry.error else "")
            for entry in entries
        ],
        limit,
    )


def _body(
    job: UploadJob,
    greeting: str,
    headline: str,
    source_folder: Optional[str] = None,
) -> str:
    lines = [greeting, "", headline, ""]
    lines += _link_lines(job.application_id)
    lines.append("")
    lines.append(f"Files received: {job.total}")
    lines.append(f"Stored: {job.stored}")
    lines.append(f"Failed: {job.failed}")

    if source_folder:
        lines.append(f"Uploaded from: {source_folder}")

    if job.error:
        lines += ["", f"Error: {job.error}"]

    failed = _file_lines(job, "failed")
    if failed:
        lines += ["", "These files did not make it:"] + failed

    stored = _file_lines(job, "stored")
    if stored:
        lines += ["", "Stored:"] + stored

    lines += ["", "-- Hive"]
    return "\n".join(lines)


def _send(recipients: Sequence[User], subject: str, body: str) -> bool:
    return send_email([user.email for user in recipients], subject, body)


def notify_upload_finished(
    recipients: Sequence[User],
    job: UploadJob,
    source_folder: Optional[str] = None,
) -> bool:
    if not recipients:
        return False

    greeting = f"Hello {_display_name(recipients[0])},"

    if job.failed:
        subject = (
            f"Document upload partly failed -- {job.failed} of {job.total} files"
        )
        headline = (
            f"{job.stored} of {job.total} documents were moved into storage; "
            f"{job.failed} could not be."
        )
    else:
        subject = f"Documents ready -- {job.stored} file(s) uploaded"
        headline = (
            f"All {job.stored} document(s) have finished moving into storage "
            "and are ready to work on."
        )

    return _send(
        recipients, subject, _body(job, greeting, headline, source_folder)
    )


def notify_upload_failed(
    recipients: Sequence[User],
    job: UploadJob,
    source_folder: Optional[str] = None,
) -> bool:
    if not recipients:
        return False

    greeting = f"Hello {_display_name(recipients[0])},"
    subject = f"Document upload failed -- application {job.application_id[:8]}"
    headline = (
        "The documents uploaded for this application could not be moved into "
        "storage. Nothing has been recorded against the application; the "
        "upload needs to be retried."
    )
    return _send(
        recipients, subject, _body(job, greeting, headline, source_folder)
    )


def notify_deid_finished(
    recipients: Sequence[User],
    summary: DeidBatchSummary,
    source_folder: Optional[str] = None,
) -> bool:
    if not recipients:
        return False

    greeting = f"Hello {_display_name(recipients[0])},"

    if summary.failed and not summary.deidentified:
        subject = (
            f"De-identification failed -- application {summary.application_id[:8]}"
        )
        headline = (
            f"None of the {summary.total} document(s) could be de-identified. "
            "The originals are untouched; the run needs to be retried."
        )
    elif summary.failed:
        subject = (
            f"De-identification partly failed -- {summary.failed} of "
            f"{summary.total} files"
        )
        headline = (
            f"{summary.deidentified} of {summary.total} document(s) were "
            f"de-identified; {summary.failed} could not be."
        )
    else:
        subject = (
            f"De-identification complete -- {summary.deidentified} file(s) ready"
        )
        headline = (
            f"All {summary.deidentified} document(s) have been de-identified "
            "and are ready for review."
        )

    lines = [greeting, "", headline, ""]
    lines += _link_lines(summary.application_id)
    lines.append("")
    lines.append(f"Documents de-identified: {summary.deidentified}")
    lines.append(f"Failed: {summary.failed}")

    if source_folder:
        lines.append(f"Uploaded from: {source_folder}")

    failed = _name_lines(summary.failed_names)
    if failed:
        lines += ["", "These documents were not de-identified:"] + failed

    ready = _name_lines(summary.deidentified_names)
    if ready:
        lines += ["", "De-identified:"] + ready

    lines += ["", "-- Hive"]
    return _send(recipients, subject, "\n".join(lines))
