"""The patient consent matrix (spec 9.2.1).

Each row records one decision: a patient's consent of a type (research, or
documents: their PDFs and images) granted, refused or withdrawn, with the
form version and date. Rows are only added, never changed, so the history
stays; a patient's latest decision of a type is the one that counts (by
consent date, then when it was recorded). REDCap can later fill the same
table.

The rule applied to projects: a patient whose latest research consent is
refused or withdrawn can't be in any project; for a project approved for
documents, the same goes for their documents consent. A patient with no
row for a type is left to the project's "Patient consent confirmed" box,
which is still required to prepare.

The import reads a spreadsheet with the columns Patient code, Consent type,
Status, Version, Consent date and Note.
"""

from datetime import date
from typing import Dict, List, Optional, Tuple

from pydantic import ValidationError as PydanticError

from app.crud import consents as crud
from app.crud import patients as patients_crud
from app.errors import ValidationError
from app.logging_setup import get_logger
from app.patient_import import _date, _key, _read_rows, _text
from app.project_schemas import (
    CONSENT_STATUSES,
    CONSENT_TYPES,
    Consent,
    ConsentCreate,
    ConsentImportResult,
    ConsentImportRow,
    Project,
)

log = get_logger(__name__)

MAX_ROWS = 50000
BLOCKING = ("refused", "withdrawn")

Latest = Dict[str, Dict[str, Consent]]


def _order(consent: Consent) -> Tuple[str, str]:
    return (consent.consent_date.isoformat() if consent.consent_date else "", consent.recorded_at or "")


def latest(cursor, patient_id: Optional[str] = None) -> Latest:
    """patient code -> consent type -> their latest decision."""
    out: Latest = {}
    for consent in sorted(crud.list_consents(cursor, patient_id), key=_order):
        out.setdefault(consent.patient_id, {})[consent.consent_type] = consent
    return out


def needed_types(project: Project) -> Tuple[str, ...]:
    return CONSENT_TYPES if project.documents_approved else ("research",)


def exclusion_reason(project: Project, decisions: Dict[str, Consent]) -> Optional[str]:
    """Why the consent matrix keeps this patient out of the project, or None."""
    for consent_type in needed_types(project):
        decision = decisions.get(consent_type)
        if decision and decision.status in BLOCKING:
            when = f" on {decision.consent_date.isoformat()}" if decision.consent_date else ""
            return f"{consent_type} consent {decision.status}{when}"
    return None


def excluded(cursor, project: Project, patient_ids: List[str]) -> Dict[str, str]:
    """The patients among `patient_ids` the consent matrix keeps out, with why."""
    matrix = latest(cursor)
    out = {}
    for code in patient_ids:
        reason = exclusion_reason(project, matrix.get(code, {}))
        if reason:
            out[code] = reason
    return out


def refuse_excluded(cursor, project: Project, patient_ids: List[str]) -> None:
    blocked = excluded(cursor, project, patient_ids)
    if blocked:
        listed = "; ".join(f"{code}: {why}" for code, why in sorted(blocked.items())[:10])
        raise ValidationError(
            f"{len(blocked)} patient(s) can't be in this project because of the "
            f"consent matrix. Take them out of the cohort: {listed}"
        )


# --- import --------------------------------------------------------------------

COLUMNS = {
    "patientcode": "patient_id",
    "code": "patient_id",
    "patientid": "patient_id",
    "consenttype": "consent_type",
    "type": "consent_type",
    "status": "status",
    "version": "version",
    "formversion": "version",
    "consentdate": "consent_date",
    "date": "consent_date",
    "note": "note",
}
LABELS = ("Patient code", "Consent type", "Status", "Version", "Consent date", "Note")


def template_csv() -> bytes:
    return ("﻿" + ",".join(LABELS) + "\r\n").encode("utf-8")


def _parse(values: dict) -> Tuple[Optional[ConsentCreate], List[str]]:
    errors = []
    day, problem = _date(values.get("consent_date"))
    if problem:
        errors.append(f"Consent date: {problem}")
    fields = {
        "patient_id": _text(values.get("patient_id")) or "",
        "consent_type": (_text(values.get("consent_type")) or "").lower(),
        "status": (_text(values.get("status")) or "").lower(),
        "version": _text(values.get("version")),
        "note": _text(values.get("note")),
        "consent_date": day,
    }
    if not fields["patient_id"]:
        errors.append("Patient code is missing")
    if fields["consent_type"] not in CONSENT_TYPES:
        errors.append(f"Consent type must be one of {', '.join(CONSENT_TYPES)}")
    if fields["status"] not in CONSENT_STATUSES:
        errors.append(f"Status must be one of {', '.join(CONSENT_STATUSES)}")
    if errors:
        return None, errors
    try:
        return ConsentCreate(**fields), []
    except PydanticError as e:
        return None, [p["msg"] for p in e.errors()]


def _same(entry: ConsentCreate, current: Optional[Consent]) -> bool:
    return bool(current) and (
        current.status == entry.status
        and (current.version or None) == entry.version
        and current.consent_date == entry.consent_date
    )


def import_file(
    cursor, name: str, data: bytes, apply: bool, actor_id: Optional[str]
) -> ConsentImportResult:
    rows = _read_rows(name, data)
    while rows and not any(_text(v) for v in rows[0]):
        rows.pop(0)
    if not rows:
        raise ValidationError("The file is empty")
    if len(rows) - 1 > MAX_ROWS:
        raise ValidationError(f"At most {MAX_ROWS} rows at a time; split the file")
    columns = [COLUMNS.get(_key(h)) for h in rows[0]]
    if "patient_id" not in columns or "status" not in columns or "consent_type" not in columns:
        raise ValidationError("The first row needs Patient code, Consent type and Status columns")

    parsed: List[Tuple[ConsentImportRow, Optional[ConsentCreate]]] = []
    for line, raw in enumerate(rows[1:], start=2):
        if not any(_text(v) for v in raw):
            continue
        values = {c: v for c, v in zip(columns, raw) if c}
        entry, errors = _parse(values)
        row = ConsentImportRow(
            line=line,
            code=(entry.patient_id if entry else _text(values.get("patient_id")) or ""),
            consent_type=entry.consent_type if entry else "",
            status=entry.status if entry else "",
            action="error" if errors else "add",
            errors=errors,
        )
        parsed.append((row, entry))

    known = patients_crud.existing_ids(cursor, [e.patient_id for _, e in parsed if e])
    matrix = latest(cursor)
    to_add: List[ConsentCreate] = []
    for row, entry in parsed:
        if entry is None:
            continue
        if entry.patient_id not in known:
            row.action, row.errors = "error", [f"No patient '{entry.patient_id}'"]
        elif _same(entry, matrix.get(entry.patient_id, {}).get(entry.consent_type)):
            row.action = "unchanged"
        else:
            to_add.append(entry)

    if apply and to_add:
        crud.insert_many(cursor, to_add, "import", actor_id)
    counts = {action: 0 for action in ("add", "unchanged", "error")}
    for row, _entry in parsed:
        counts[row.action] += 1
    log.info("consent_import", applied=apply, **counts)
    return ConsentImportResult(applied=apply, counts=counts, rows=[r for r, _ in parsed])


def record(cursor, entry: ConsentCreate, actor_id: str) -> Consent:
    if not patients_crud.existing_ids(cursor, [entry.patient_id]):
        raise ValidationError(f"No patient '{entry.patient_id}'")
    if entry.consent_date and entry.consent_date > date.today():
        raise ValidationError("The consent date is in the future")
    return crud.insert_many(cursor, [entry], "manual", actor_id)[0]
