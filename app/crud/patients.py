"""Patient CRUD, against the singular `patient` table."""
from datetime import date, datetime
from typing import List, Optional

from app.db import execute
from app.errors import ConflictError, NotFoundError, ValidationError
from app.ids import new_patient_id
from app.logging_setup import get_logger
from app.schemas import (
    PATIENT_FILE_REQUIRED,
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
    # patient identity
    "fstname",
    "lstname",
    # provider / institution
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
    # patient's own contact details
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
    # dates
    "dt_reg",
    "dt_b",
    "dt_d",
    # source documents
    "original_file_path",
    "deidentified_file_path",
)

DATE_COLUMNS = frozenset({"dt_reg", "dt_b", "dt_d"})

_COLS = ", ".join(f"`{c}`" for c in COLUMNS)


def _placeholder(column: str) -> str:
    return "CAST(%s AS DATE)" if column in DATE_COLUMNS else "%s"


def _to_date(value) -> Optional[date]:
    """Hive drivers hand DATE back as either a date or an ISO string depending on the transport, so both are accepted."""
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
    # No UNIQUE constraints in Hive -- pre-check SELECTs, non-atomic.
    for column, label in _UNIQUE_COLUMNS:
        value = values.get(column)
        if not value:
            continue
        clash = _find_by(cursor, column, value)
        if clash and clash != exclude_id:
            raise ConflictError(f"{label} '{value}' already exists")


def create_patient(cursor, payload: PatientCreate) -> Patient:
    fields = payload.model_dump()
    _assert_unique(cursor, fields)

    patient_id = new_patient_id(lambda candidate: _id_exists(cursor, candidate))

    fields["id"] = patient_id
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


def update_patient(cursor, patient_id: str, payload: PatientUpdate) -> Patient:
    existing = get_patient_or_404(cursor, patient_id)

    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        return existing

    merged = {**existing.model_dump(), **fields}
    if not patient_has_identity(merged):
        raise ValidationError(PATIENT_IDENTITY_REQUIRED)
    if not merged.get("original_file_path"):
        raise ValidationError(PATIENT_FILE_REQUIRED)

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
