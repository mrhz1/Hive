"""Intake emails, to every active user whose role has `deidentifier:notify`.

- new files waiting in the incoming folder (scripts/intake_notify.py, run as
  a scheduled job: it only mentions files that arrived since its last email);
- an intake run finished: how many were done, failed, set aside;
- an application or a document was rejected, with the reason.

A failed send never raises (see app.mailer); these return whether an email
went out.
"""

import os
import time
from collections import Counter
from typing import Iterable, List, Optional

from app import intake
from app.crud import users as users_crud
from app.db import hive_cursor
from app.logging_setup import get_logger
from app.mailer import send_email
from app.schemas import ENROLLMENT_CHECKS, User

log = get_logger(__name__)

NOTIFY_PERMISSION = "deidentifier:notify"
STATE_FILE = "notices.json"
LIST_LIMIT = 20


def recipients(cursor) -> List[User]:
    return [
        user
        for user in users_crud.list_users(cursor)
        if user.is_active and user.email and NOTIFY_PERMISSION in user.permissions
    ]


def _page(path: str) -> Optional[str]:
    base = (os.environ.get("APP_BASE_URL") or "").strip().rstrip("/")
    return f"{base}{path}" if base else None


def _send(people: List[User], subject: str, lines: Iterable[str]) -> bool:
    if not people:
        log.info("intake_notice_no_recipients", subject=subject)
        return False
    body = "\n".join(["Hello,", "", *lines, "", "-- Hive"])
    return send_email([user.email for user in people], subject, body)


def _send_to_team(subject: str, lines: List[str], cursor=None) -> bool:
    try:
        if cursor is not None:
            return _send(recipients(cursor), subject, lines)
        with hive_cursor() as own:
            return _send(recipients(own), subject, lines)
    except Exception as e:
        log.error("intake_notice_failed", subject=subject, error=str(e))
        return False


def _counted(codes: Counter) -> List[str]:
    lines = [f"  {code}: {count}" for code, count in codes.most_common(LIST_LIMIT)]
    if len(codes) > LIST_LIMIT:
        lines.append(f"  ... and {len(codes) - LIST_LIMIT} more")
    return lines


# --- new files ---------------------------------------------------------------


def _state_path():
    return intake.state_dir() / STATE_FILE


def new_files(since: float):
    """Settled files in the incoming folder touched after `since`, and the
    newest time among them."""
    found, newest = [], since
    root = intake.intake_root()
    for path in intake.walk(root):
        if intake.is_extra_file(path.name) or not intake.is_settled(path):
            continue
        try:
            touched = intake.last_touched(path.stat())
        except OSError:
            continue
        if touched > since:
            found.append(path.relative_to(root).as_posix())
            newest = max(newest, touched)
    return found, newest


def notify_new_files(cursor=None) -> dict:
    state = intake.read_json(_state_path()) or {}
    since = float(state.get("files_seen_until") or 0)

    found, newest = new_files(since)
    if not found:
        return {"new": 0, "sent": False}

    codes = Counter(intake.detect(relative).code or "no code" for relative in found)
    waiting = intake.count_files(intake.intake_root())
    page = _page("/intake")

    lines = [
        f"{len(found)} new file(s) arrived for intake "
        f"({waiting} waiting in total).",
        "",
        "By patient code:",
        *_counted(codes),
        "",
        f"Start de-identification on the Intake page{': ' + page if page else '.'}",
    ]
    sent = _send_to_team(f"New intake files: {len(found)}", lines, cursor)

    # Only move on when the email went out, so nothing is skipped silently.
    if sent:
        intake.write_json(
            _state_path(), dict(state, files_seen_until=newest, notified_at=time.time())
        )
    log.info("intake_new_files_notice", new=len(found), sent=sent)
    return {"new": len(found), "sent": sent}


# --- a run finished ------------------------------------------------------------


def notify_run_finished(report: dict) -> bool:
    done = int(report.get("done") or 0)
    failed = int(report.get("failed") or 0)
    aside = int(report.get("set_aside") or 0)
    if not (done or failed or aside):
        return False

    page = _page("/intake")
    lines = [
        "An intake run has finished.",
        "",
        f"De-identified: {done}",
        f"Failed: {failed}",
        f"Need attention (no code, conflict, duplicate, unsupported): {aside}",
    ]
    if failed or aside:
        lines += ["", "The failed and need-attention lists are on the Intake page."]
    if page:
        lines.append(page)

    subject = (
        f"Intake run finished: {done} done, {failed} failed, {aside} need attention"
    )
    return _send_to_team(subject, lines)


# --- rejections ----------------------------------------------------------------


def notify_application_rejected(
    application_id: str,
    patient_id: str,
    actor: User,
    failed_checks: List[str],
    reason: str,
    deleted: bool,
) -> bool:
    page = _page(f"/applications/{application_id}")
    lines = [
        f"The application for patient {patient_id} was rejected by {actor.username}.",
        "",
        "What failed:",
        *[f"  - {ENROLLMENT_CHECKS.get(key, key)}" for key in failed_checks],
        "",
        f"Reason: {reason}",
        "",
    ]
    if deleted:
        lines.append(
            "There is no consent, so all of its documents (originals and "
            "de-identified copies) were deleted. Only the record is kept."
        )
    else:
        lines.append("It can be fixed and submitted again.")
    if page:
        lines += ["", page]

    subject = (
        f"Application rejected and deleted: {patient_id}"
        if deleted
        else f"Application rejected: {patient_id}"
    )
    return _send_to_team(subject, lines)


def notify_file_rejected(
    application_id: str,
    patient_id: str,
    file_name: str,
    actor: User,
    note: str,
) -> bool:
    page = _page("/rejections")
    lines = [
        f"A document of patient {patient_id} was rejected by {actor.username}.",
        "",
        f"Document: {file_name}",
        f"Reason: {note}",
        "",
        "Replace its de-identified copy or delete it from Rejections"
        + (f": {page}" if page else "."),
    ]
    return _send_to_team(f"Document rejected: {patient_id}", lines)
