import os
import time
from collections import Counter
from typing import Iterable, List, Optional

from app import intake
from app.crud import institutions as institutions_crud
from app.crud import patient_applications as applications_crud
from app.crud import patients as patients_crud
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


def _state_path():
    return intake.state_dir() / STATE_FILE


def new_files(since: float):
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

    if sent:
        intake.write_json(
            _state_path(), dict(state, files_seen_until=newest, notified_at=time.time())
        )
    log.info("intake_new_files_notice", new=len(found), sent=sent)
    return {"new": len(found), "sent": sent}


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


def notify_copy_finished(job: dict) -> bool:
    done = int(job.get("done") or 0)
    failed = int(job.get("failed") or 0)
    total = int(job.get("total") or 0)
    errors = list(job.get("errors") or [])
    if not (done or failed or errors):
        return False

    started_at = job.get("started_at")
    finished_at = job.get("finished_at")
    page = _page("/intake")

    lines = ["A copy from Carbon into intake has finished.", ""]
    if job.get("started_by"):
        lines.append(f"Started by: {job['started_by']}")
    if started_at and finished_at:
        lines.append(f"Took: {max(0, round(finished_at - started_at))} seconds")
    lines += [
        f"Copied: {done} of {total}",
        f"Failed: {failed}",
        f"Skipped (already in intake or processed): {int(job.get('skipped') or 0)}",
    ]
    if errors:
        lines += ["", "Problems:", *[f"  {e}" for e in errors[:LIST_LIMIT]]]
    if done:
        lines += ["", "The files are waiting on the Intake page for de-identification."]
    if page:
        lines.append(page)

    if done and not (failed or errors):
        subject = f"Carbon copy finished: {done} file(s) copied"
    elif done:
        subject = f"Carbon copy partly failed: {done} copied, {failed} failed"
    else:
        subject = f"Carbon copy failed: 0 of {total} copied"
    return _send_to_team(subject, lines)


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
            "The patient is not eligible, so all of its documents (originals "
            "and de-identified copies) were deleted. Only the record is kept; "
            "the submission has to start again."
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


def site_contact(cursor, patient_id: str) -> Optional[dict]:
    """The saved contact of the patient's institution, if it has an email."""
    patient = patients_crud.get_patient(cursor, patient_id)
    code = institutions_crud.normalise(getattr(patient, "instcode", None))
    if not code:
        return None
    site = institutions_crud.get(cursor, code)
    return site if site and site.get("contact_email") else None


def notify_site_rejected(
    application_id: str,
    patient_id: str,
    failed_checks: List[str],
    reason: str,
    deleted: bool,
) -> bool:
    """Tell the submitting site why its submission was rejected (protocol
    9.1.2 step 7). Reasons 1, 3 and 4 give the UBRS for the resubmission;
    reason 2 (not eligible) purges everything, so the code is left out."""
    try:
        with hive_cursor() as cursor:
            site = site_contact(cursor, patient_id)
            if not site:
                log.info("site_notice_no_contact", application_id=application_id)
                return False
            application = applications_crud.get_application_or_404(cursor, application_id)
    except Exception as e:
        log.error("site_notice_failed", application_id=application_id, error=str(e))
        return False

    received = str(application.created_at or "")[:10]
    lines = [
        f"A submission from {site.get('name') or site['code']}"
        + (f" received on {received}" if received else "")
        + " was rejected by the CHSS team.",
        "",
        "Checks that were not met:",
        *[f"  - {ENROLLMENT_CHECKS.get(key, key)}" for key in failed_checks],
        "",
        f"Reason: {reason}",
        "",
    ]
    if deleted:
        lines.append(
            "The patient is not eligible, so every file of this submission was "
            "deleted. If you believe this is wrong, contact the CHSS team; "
            "otherwise no action is needed."
        )
        subject = "CHSS submission rejected: patient not eligible"
    else:
        lines.append(
            f"Please correct the submission and send it again under the patient "
            f"code {patient_id}."
        )
        subject = f"CHSS submission rejected: {patient_id}"
    try:
        sent = send_email([site["contact_email"]], subject, "\n".join(["Hello,", "", *lines, "", "-- CHSS"]))
    except Exception as e:
        log.error("site_notice_failed", application_id=application_id, error=str(e))
        return False
    log.info("site_notice_sent", application_id=application_id, site=site["code"], sent=sent)
    return sent
