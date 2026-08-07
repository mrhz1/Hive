"""Patient application CRUD.

An application is the workflow wrapper around a patient record: who
submitted it, who reviewed it, and where it is in the process. The
clinical facts live on the patient; this holds the provenance.

HiveQL only: %s paramstyle, backtick identifiers, no
RETURNING/ON CONFLICT/sequences.
"""
import uuid
from typing import Any, List, Optional

from app.db import NOW_SQL, NULL_TIMESTAMP_SQL, execute
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

# These are never bound as parameters -- Hive only stores a timestamp
# written as SQL text (see db.NOW_SQL), so each of them is either the
# server clock or a typed NULL, and neither consumes a placeholder.
TIMESTAMP_COLUMNS = frozenset(
    {"submitted_at", "created_at", "updated_at", "reviewed_at"}
)

# Sentinel for "stamp this column with the server clock". A timestamp
# column's value is one of NOW or None; there is no third case, because
# no caller may supply a timestamp of their own.
NOW = object()

_COLS = ", ".join(f"`{c}`" for c in COLUMNS)


def _value_sql(column: str, value: Any) -> tuple:
    """The SQL text for one column's value, plus the params it binds.

    Timestamps inline their SQL and bind nothing; everything else is a
    plain placeholder.
    """
    if column in TIMESTAMP_COLUMNS:
        return (NOW_SQL if value is NOW else NULL_TIMESTAMP_SQL), ()
    return "%s", (value,)


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
        "submitted_at": NOW if payload.status == "submitted" else None,
        "created_at": NOW,
        "updated_at": NOW,
        "reviewed_at": None,
    }

    values, params = [], []
    for column in COLUMNS:
        value_sql, bound = _value_sql(column, fields[column])
        values.append(value_sql)
        params.extend(bound)

    execute(
        cursor,
        f"INSERT INTO `patient_applications` ({_COLS}) "
        f"VALUES ({', '.join(values)})",
        tuple(params),
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

    # Every write records who made it and when, even one that only
    # changes the description -- that is the point of the column.
    fields["updated_by_id"] = actor_id
    fields["updated_at"] = NOW

    # Status transitions stamp their own actor. Only on the transition:
    # re-saving an already-submitted application must not rewrite who
    # submitted it, or the audit trail becomes whoever touched it last.
    status = fields.get("status")
    if status == "submitted" and existing.status != "submitted":
        fields["submitted_by_id"] = actor_id
        fields["submitted_at"] = NOW
    elif status in ("approved", "rejected") and existing.status != status:
        fields["reviewed_by_id"] = actor_id
        fields["reviewed_at"] = NOW

    set_parts, params = [], []
    for column, value in fields.items():
        value_sql, bound = _value_sql(column, value)
        set_parts.append(f"`{column}` = {value_sql}")
        params.extend(bound)

    execute(
        cursor,
        f"UPDATE `patient_applications` SET {', '.join(set_parts)} "
        "WHERE `id` = %s",
        tuple(params) + (application_id,),
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
