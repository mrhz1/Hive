from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from pydantic import BaseModel

from app import consent
from app.crud import patients as patients_crud

RECENT_DAYS = 365
HANDOVER_AGE = 15
ADULT_AGE = 18


class FollowupRow(BaseModel):
    patient_id: str
    first_name: Optional[str] = None
    email: Optional[str] = None
    consent_version: Optional[str] = None
    consent_update: Optional[str] = None
    reasons: List[str] = []


class FollowupResult(BaseModel):
    automated: List[FollowupRow]
    manual: List[FollowupRow]
    not_contacted: List[FollowupRow]


def _as_date(value) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _age(born: Optional[date], on: date) -> Optional[int]:
    if not born:
        return None
    return on.year - born.year - ((on.month, on.day) < (born.month, born.day))


def _consent_update(born: Optional[date], signed: Optional[date], today: date) -> Optional[str]:
    age = _age(born, today)
    if age is None:
        return None
    signed_age = _age(born, signed) if signed else None
    if age >= ADULT_AGE and (signed_age is None or signed_age < ADULT_AGE):
        return f"turned {ADULT_AGE}: own consent needed"
    if age >= HANDOVER_AGE and (signed_age is None or signed_age < HANDOVER_AGE):
        return f"{HANDOVER_AGE} or older: may take over follow-up"
    return None


def eligibility(cursor, current_version: Optional[str] = None, recent_days: int = RECENT_DAYS,
                today: Optional[date] = None) -> FollowupResult:
    today = today or datetime.now(timezone.utc).date()
    wanted_version = (current_version or "").strip() or None
    recent_since = today - timedelta(days=recent_days)
    matrix = consent.latest(cursor)
    automated, manual, not_contacted = [], [], []

    for patient in sorted(patients_crud.list_patients(cursor), key=lambda p: p.id):
        decisions = matrix.get(patient.id, {})
        research = decisions.get("research")
        row = FollowupRow(
            patient_id=patient.id,
            first_name=patient.fstname,
            email=patient.ptemail,
            consent_version=research.version if research else None,
        )

        if patient.dt_d:
            row.reasons = ["deceased"]
            not_contacted.append(row)
            continue
        if research and research.status in consent.BLOCKING:
            row.reasons = [f"research consent {research.status}"]
            not_contacted.append(row)
            continue
        if patient.no_records:
            row.reasons = ["the site does its own follow-up (shares no records)"]
            not_contacted.append(row)
            continue

        reasons = []
        if not research or research.status != "granted":
            reasons.append("no research consent on record")
        elif wanted_version and (research.version or "") != wanted_version:
            reasons.append(f"consent form is version {research.version or '?'}, not {wanted_version}")
        checked = _as_date(patient.details_checked_at)
        if not checked or checked < recent_since:
            reasons.append(f"no follow-up from the site in the last {recent_days} days")
        online = decisions.get("online_followup")
        if not online or online.status != "granted":
            reasons.append("online follow-up not chosen")
        if not patient.ptemail:
            reasons.append("no email address")

        row.reasons = reasons
        if reasons:
            manual.append(row)
        else:
            row.consent_update = _consent_update(
                _as_date(patient.dt_b), research.consent_date if research else None, today
            )
            automated.append(row)

    return FollowupResult(automated=automated, manual=manual, not_contacted=not_contacted)


def workbook(result: FollowupResult, current_version: Optional[str]) -> bytes:
    from io import BytesIO

    from openpyxl import Workbook
    from openpyxl.styles import Font

    from app.safe_cells import row as safe_row

    book = Workbook()
    sheets = [
        ("Automated", ["patient_id", "first_name", "email", "consent_version", "consent_update", "survey_link"],
         [[r.patient_id, r.first_name, r.email, r.consent_version, r.consent_update or "", ""] for r in result.automated]),
        ("Manual", ["patient_id", "first_name", "email", "why not automated"],
         [[r.patient_id, r.first_name, r.email, "; ".join(r.reasons)] for r in result.manual]),
        ("Not contacted", ["patient_id", "why"],
         [[r.patient_id, "; ".join(r.reasons)] for r in result.not_contacted]),
        ("About", ["item", "value"],
         [["rules", "protocol 9.1.14-9.1.15"],
          ["current consent version", current_version or "(any granted)"],
          ["survey_link", "filled by REDCap once the API is connected"]]),
    ]
    for index, (title, header, rows) in enumerate(sheets):
        sheet = book.active if index == 0 else book.create_sheet()
        sheet.title = title
        sheet.append(safe_row(header))
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        for values in rows:
            sheet.append(safe_row(["" if v is None else str(v) for v in values]))
    out = BytesIO()
    book.save(out)
    return out.getvalue()
