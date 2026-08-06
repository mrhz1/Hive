"""Patient application CRUD.

An application is the workflow wrapper around a patient record: who
submitted it, who reviewed it, and where it is in the process. The
clinical facts live on the patient; this holds the provenance.

HiveQL only: %s paramstyle, backtick identifiers, no
RETURNING/ON CONFLICT/sequences.
"""
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from app.db import execute
from app.errors import NotFoundError
from app.logging_setup import get_logger
from app.schemas import (
    PatientApplication,
    PatientApplicationCreate,
    PatientApplicationUpdate,
)

log = get_logger(__name__)

# Column order is the single source of truth for SELECT/INSERT and for
# mapping a row back onto the model -- adding a column means adding it
# here (and to sql/schema.sql) and nowhere else.
COLUMNS = (
    "id",
    "patient_id",
    "submitted_by_id",
    "reviewed_by_id",
    "status",
    "submitted_at",
    "reviewed_at",
    "created_at",
    "updated_at",
    "description",
    "created_by_id",
    "updated_by_id",
)

# Hive will not implicitly cast a bound STRING parameter into a TIMESTAMP
# column, so these get an explicit CAST in INSERT/UPDATE. CAST(NULL AS
# TIMESTAMP) is valid, so a nullable value needs no special case.
TIMESTAMP_COLUMNS = frozenset(
    {"submitted_at", "created_at", "updated_at", "reviewed_at"}
)

_COLS = ", ".join(f"`{c}`" for c in COLUMNS)


def _placeholder(column: str) -> str:
    return "CAST(%s AS TIMESTAMP)" if column in TIMESTAMP_COLUMNS else "%s"


def _now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")


def _row_to_application(row) -> PatientApplication:
    return PatientApplication(**dict(zip(COLUMNS, row)))


def get_application(cursor, application_id: str) -> Optional[PatientApplication]:
    execute(
        cursor,
        f"SELECT {_COLS} FROM `patient_applications` WHERE `id` = %s",
        (application_id,),
    )
    row = cursor.fetchone()
    return _row_to_application(row) if row else None


def get_application_or_404(cursor, application_id: str) -> PatientApplication:
    found = get_application(cursor, application_id)
    if found is None:
        raise NotFoundError(f"Application '{application_id}' not found")
    return found


def list_applications(
    cursor, patient_id: Optional[str] = None
) -> List[PatientApplication]:
    sql = f"SELECT {_COLS} FROM `patient_applications`"
    params: tuple = ()
    if patient_id:
        sql += " WHERE `patient_id` = %s"
        params = (patient_id,)
    sql += " ORDER BY `created_at` DESC"

    execute(cursor, sql, params)
    return [_row_to_application(r) for r in cursor.fetchall()]


def create_application(
    cursor, payload: PatientApplicationCreate, actor_id: str
) -> PatientApplication:
    application_id = str(uuid.uuid4())
    now = _now()

    fields = {
        "id": application_id,
        "patient_id": payload.patient_id,
        # Submission is a transition, not a creation: an application
        # created straight into 'submitted' is submitted by its creator,
        # but a draft has nobody as submitter yet.
        "submitted_by_id": actor_id if payload.status == "submitted" else None,
        "reviewed_by_id": None,
        "status": payload.status,
        "description": payload.description,
        "created_by_id": actor_id,
        "updated_by_id": actor_id,
        "submitted_at": now if payload.status == "submitted" else None,
        "created_at": now,
        "updated_at": now,
        "reviewed_at": None,
    }

    placeholders = ", ".join(_placeholder(c) for c in COLUMNS)
    execute(
        cursor,
        f"INSERT INTO `patient_applications` ({_COLS}) VALUES ({placeholders})",
        tuple(fields[c] for c in COLUMNS),
    )
    log.info(
        "application_created",
        application_id=application_id,
        patient_id=payload.patient_id,
        status=payload.status,
    )
    return get_application_or_404(cursor, application_id)


def update_application(
    cursor, application_id: str, payload: PatientApplicationUpdate, actor_id: str
) -> PatientApplication:
    existing = get_application_or_404(cursor, application_id)

    fields = payload.model_dump(exclude_unset=True)
    now = _now()

    # Every write records who made it and when, even one that only
    # changes the description -- that is the point of the column.
    fields["updated_by_id"] = actor_id
    fields["updated_at"] = now

    # Status transitions stamp their own actor. Only on the transition:
    # re-saving an already-submitted application must not rewrite who
    # submitted it, or the audit trail becomes whoever touched it last.
    status = fields.get("status")
    if status == "submitted" and existing.status != "submitted":
        fields["submitted_by_id"] = actor_id
        fields["submitted_at"] = now
    elif status in ("approved", "rejected") and existing.status != status:
        fields["reviewed_by_id"] = actor_id
        fields["reviewed_at"] = now

    set_clause = ", ".join(f"`{c}` = {_placeholder(c)}" for c in fields)
    params = tuple(fields.values()) + (application_id,)
    execute(
        cursor,
        f"UPDATE `patient_applications` SET {set_clause} WHERE `id` = %s",
        params,
    )
    log.info(
        "application_updated", application_id=application_id, fields=sorted(fields)
    )
    return get_application_or_404(cursor, application_id)


def delete_application(cursor, application_id: str) -> PatientApplication:
    existing = get_application_or_404(cursor, application_id)
    execute(
        cursor,
        "DELETE FROM `patient_applications` WHERE `id` = %s",
        (application_id,),
    )
    log.info("application_deleted", application_id=application_id)
    return existing


def delete_applications_for_patient(
    cursor, patient_id: str
) -> List[PatientApplication]:
    """Used when a patient is removed, so their applications do not linger
    as rows pointing at a patient that no longer exists."""
    existing = list_applications(cursor, patient_id)
    if existing:
        execute(
            cursor,
            "DELETE FROM `patient_applications` WHERE `patient_id` = %s",
            (patient_id,),
        )
        log.info(
            "applications_deleted", patient_id=patient_id, count=len(existing)
        )
    return existing
