from datetime import date, datetime, timezone
from typing import Dict, List, Optional

from app.db import authoritative, execute
from app.errors import ConflictError, NotFoundError, ValidationError
from app.logging_setup import get_logger
from app.schemas import (
    PATIENT_IDENTIFIERS,
    PATIENT_IDENTITY_REQUIRED,
    Patient,
    PatientCreate,
    PatientUpdate,
    patient_has_identity,
)

log = get_logger(__name__)

COLUMNS = (
    "id",
    "fstname",
    "lstname",
    "instcode",
    "pname",
    "street",
    "street2",
    "street3",
    "city",
    "state",
    "zip",
    "country",
    "phone1",
    "phone2",
    "wphone1",
    "wphone2",
    "pemail",
    "ptstreet",
    "ptstreet2",
    "ptstreet3",
    "ptcity",
    "ptstate",
    "ptzip",
    "ptcountry",
    "ptphone",
    "ptphone2",
    "ptwphone",
    "ptwphone2",
    "ptemail",
    "dt_reg",
    "dt_b",
    "dt_d",
    "original_file_path",
    "deidentified_file_path",
    # Someone confirmed the details are right (see confirm_details). Patients
    # made by intake or the bulk import start without it.
    "details_checked_at",
    "details_checked_by",
    "no_records",
)

DATE_COLUMNS = {"dt_reg", "dt_b", "dt_d"}

_COLS = ", ".join(f"`{c}`" for c in COLUMNS)


def _placeholder(column: str) -> str:
    return "CAST(%s AS DATE)" if column in DATE_COLUMNS else "%s"


def _to_date(value) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    return date.fromisoformat(text[:10])


def _row_to_patient(row) -> Patient:
    values = dict(zip(COLUMNS, row))
    for column in DATE_COLUMNS:
        values[column] = _to_date(values[column])
    return Patient(**values)


def get_patient(cursor, patient_id: str) -> Optional[Patient]:
    execute(cursor, f"SELECT {_COLS} FROM `patient` WHERE `id` = %s", (patient_id,))
    row = cursor.fetchone()
    return _row_to_patient(row) if row else None


def get_patient_or_404(cursor, patient_id: str) -> Patient:
    patient = get_patient(cursor, patient_id)

    if patient is None:
        with authoritative(cursor):
            patient = get_patient(cursor, patient_id)

    if patient is None:
        raise NotFoundError(f"Patient '{patient_id}' not found")
    return patient


def list_patients(cursor) -> List[Patient]:
    execute(cursor, f"SELECT {_COLS} FROM `patient`")
    return [_row_to_patient(r) for r in cursor.fetchall()]


def _find_by(cursor, column: str, value: str) -> Optional[str]:
    execute(cursor, f"SELECT `id` FROM `patient` WHERE `{column}` = %s", (value,))
    row = cursor.fetchone()
    return row[0] if row else None


def _id_exists(cursor, patient_id: str) -> bool:
    return _find_by(cursor, "id", patient_id) is not None


_UNIQUE_COLUMNS = (("ptemail", "Email"), ("ptphone", "Phone number"))


def _assert_unique(cursor, values: dict, exclude_id: Optional[str] = None) -> None:
    for column, label in _UNIQUE_COLUMNS:
        value = values.get(column)
        if not value:
            continue
        clash = _find_by(cursor, column, value)
        if clash and clash != exclude_id:
            raise ConflictError(f"{label} '{value}' already exists")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_patient(
    cursor, payload: PatientCreate, checked_by: Optional[str] = None
) -> Patient:
    """`checked_by`: who typed the details in, so they count as checked."""
    fields = payload.model_dump()
    fields["details_checked_at"] = _now() if checked_by else None
    fields["details_checked_by"] = checked_by
    _assert_unique(cursor, fields)

    patient_id = fields["id"]
    if _id_exists(cursor, patient_id):
        raise ConflictError(f"Patient code '{patient_id}' already exists")
    for column in DATE_COLUMNS:
        value = fields[column]
        fields[column] = value.isoformat() if value else None

    placeholders = ", ".join(_placeholder(c) for c in COLUMNS)
    execute(
        cursor,
        f"INSERT INTO `patient` ({_COLS}) VALUES ({placeholders})",
        tuple(fields[c] for c in COLUMNS),
    )
    log.info(
        "patient_created",
        patient_id=patient_id,
        identified_by=[n for n in PATIENT_IDENTIFIERS if fields.get(n)],
    )
    return get_patient_or_404(cursor, patient_id)


def create_empty_patient(cursor, patient_id: str) -> None:
    values = [patient_id] + [None] * (len(COLUMNS) - 1)
    placeholders = ", ".join(_placeholder(c) for c in COLUMNS)
    execute(
        cursor,
        f"INSERT INTO `patient` ({_COLS}) VALUES ({placeholders})",
        tuple(values),
    )
    log.info("patient_created", patient_id=patient_id, source="intake")


def insert_many(cursor, rows: List[Dict], chunk: int = 200) -> int:
    """Insert patients in a few statements (one INSERT per row is slow on
    Hive). Rows are column -> value; missing columns are NULL."""
    placeholders = "(" + ", ".join(_placeholder(c) for c in COLUMNS) + ")"
    for start in range(0, len(rows), chunk):
        part = rows[start : start + chunk]
        params: list = []
        for row in part:
            for column in COLUMNS:
                value = row.get(column)
                if column in DATE_COLUMNS and isinstance(value, date):
                    value = value.isoformat()
                params.append(value)
        execute(
            cursor,
            f"INSERT INTO `patient` ({_COLS}) VALUES " + ", ".join([placeholders] * len(part)),
            tuple(params),
        )
    log.info("patients_inserted", count=len(rows))
    return len(rows)


def set_fields(cursor, patient_id: str, fields: Dict) -> None:
    """Write these columns as given, without the checks of update_patient
    (the bulk import fills empty fields of patients that may have no name)."""
    if not fields:
        return
    values = {
        column: value.isoformat() if isinstance(value, date) else value
        for column, value in fields.items()
    }
    set_clause = ", ".join(f"`{c}` = {_placeholder(c)}" for c in values)
    execute(
        cursor,
        f"UPDATE `patient` SET {set_clause} WHERE `id` = %s",
        tuple(values.values()) + (patient_id,),
    )


def confirm_details(cursor, patient_id: str, actor_id: str) -> Patient:
    get_patient_or_404(cursor, patient_id)
    execute(
        cursor,
        "UPDATE `patient` SET `details_checked_at` = %s, `details_checked_by` = %s "
        "WHERE `id` = %s",
        (_now(), actor_id, patient_id),
    )
    log.info("patient_details_confirmed", patient_id=patient_id)
    return get_patient_or_404(cursor, patient_id)


def existing_ids(cursor, ids: List[str]) -> set:
    found = set()
    ids = list(dict.fromkeys(ids))
    for start in range(0, len(ids), 500):
        chunk = ids[start : start + 500]
        slots = ", ".join(["%s"] * len(chunk))
        execute(cursor, f"SELECT `id` FROM `patient` WHERE `id` IN ({slots})", tuple(chunk))
        for row in cursor.fetchall():
            found.add(row[0])
    return found


def update_patient(cursor, patient_id: str, payload: PatientUpdate) -> Patient:
    existing = get_patient_or_404(cursor, patient_id)

    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        return existing

    merged = {**existing.model_dump(), **fields}
    if not merged.get("no_records") and not patient_has_identity(merged):
        raise ValidationError(PATIENT_IDENTITY_REQUIRED)

    changed = {
        column: value
        for column, value in fields.items()
        if getattr(existing, column, None) != value
    }
    _assert_unique(cursor, changed, exclude_id=patient_id)

    for column in DATE_COLUMNS & fields.keys():
        value = fields[column]
        fields[column] = value.isoformat() if value else None

    set_clause = ", ".join(f"`{c}` = {_placeholder(c)}" for c in fields)
    params = tuple(fields.values()) + (patient_id,)
    execute(cursor, f"UPDATE `patient` SET {set_clause} WHERE `id` = %s", params)
    log.info("patient_updated", patient_id=patient_id, fields=sorted(fields))
    return get_patient_or_404(cursor, patient_id)


def delete_patient(cursor, patient_id: str) -> Patient:
    existing = get_patient_or_404(cursor, patient_id)
    execute(cursor, "DELETE FROM `patient` WHERE `id` = %s", (patient_id,))
    log.info("patient_deleted", patient_id=patient_id)
    return existing
