"""Who gets told what, when a background upload finishes or falls over.

Kept apart from app/mailer.py on purpose: that module knows how to talk
to an SMTP relay and nothing about this application; this one knows the
domain and nothing about sockets.
"""
from typing import List, Optional, Sequence

from app.crud import patient_applications as applications_crud
from app.crud import users as users_crud
from app.logging_setup import get_logger
from app.mailer import send_email
from app.schemas import UploadJob, User

log = get_logger(__name__)


def _display_name(user: User) -> str:
    full = f"{user.first_name or ''} {user.last_name or ''}".strip()
    return full or user.username


def assignee_for_application(cursor, application_id: str) -> Optional[User]:
    """The user an application is assigned to, if it is assigned to anyone."""
    application = applications_crud.get_application(cursor, application_id)
    assigned_to = getattr(application, "assigned_to_id", None)
    if not assigned_to:
        return None
    return users_crud.get_user(cursor, assigned_to)


def upload_recipients(
    cursor, application_id: str, fallback_user_id: Optional[str] = None
) -> List[User]:
    """Who to tell about an upload on this application.

    The assigned user is the intended audience. When nobody is assigned
    the person who started the upload is told instead -- a batch that
    failed silently is worse than one email to the wrong-ish inbox.
    """
    assignee = assignee_for_application(cursor, application_id)
    if assignee is not None:
        return [assignee]

    if fallback_user_id:
        actor = users_crud.get_user(cursor, fallback_user_id)
        if actor is not None:
            log.info(
                "upload_notice_unassigned",
                application_id=application_id,
                falling_back_to=actor.id,
            )
            return [actor]

    log.info("upload_notice_no_recipient", application_id=application_id)
    return []


def _file_lines(job: UploadJob, status: str, limit: int = 20) -> List[str]:
    entries = [f for f in job.files if f.status == status]
    lines = [
        f"  - {entry.name}" + (f" ({entry.error})" if entry.error else "")
        for entry in entries[:limit]
    ]
    if len(entries) > limit:
        lines.append(f"  ... and {len(entries) - limit} more")
    return lines


def _body(job: UploadJob, greeting: str, headline: str) -> str:
    lines = [greeting, "", headline, ""]
    lines.append(f"Application: {job.application_id}")
    lines.append(f"Files received: {job.total}")
    lines.append(f"Stored: {job.stored}")
    lines.append(f"Failed: {job.failed}")

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


def notify_upload_finished(recipients: Sequence[User], job: UploadJob) -> bool:
    """Success, or success-with-casualties. Both are worth an email."""
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

    return _send(recipients, subject, _body(job, greeting, headline))


def notify_upload_failed(recipients: Sequence[User], job: UploadJob) -> bool:
    """The batch never got off the ground, or every file in it failed."""
    if not recipients:
        return False

    greeting = f"Hello {_display_name(recipients[0])},"
    subject = f"Document upload failed -- application {job.application_id[:8]}"
    headline = (
        "The documents uploaded for this application could not be moved into "
        "storage. Nothing has been recorded against the application; the "
        "upload needs to be retried."
    )
    return _send(recipients, subject, _body(job, greeting, headline))
