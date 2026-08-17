"""Patient application CRUD."""
import uuid
from typing import Any, List, Optional

from app.db import NOW_SQL, NULL_TIMESTAMP_SQL, authoritative, execute
from app.errors import NotFoundError
from app.logging_setup import get_logger
from app.schemas import (
    PatientApplication,
    PatientApplicationCreate,
    PatientApplicationUpdate,
)

log = get_logger(__name__)

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
    "status_reason",
    "assigned_to_id",
    "original_file_path",
)

TIMESTAMP_COLUMNS = frozenset(
    {"submitted_at", "created_at", "updated_at", "reviewed_at"}
)

NOW = object()

_COLS = ", ".join(f"`{c}`" for c in COLUMNS)


def _value_sql(column: str, value: Any) -> tuple:
    """The SQL text for one column's value, plus the params it binds."""
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
        # A miss may only mean the query engine has not caught up with a
        # row written a moment ago. Ask the engine that owns it first.
        with authoritative(cursor):
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


def newest_for_patient(cursor, patient_id: str) -> Optional[PatientApplication]:
    """The patient's most recent application, or None."""
    applications = list_applications(cursor, patient_id)
    return applications[0] if applications else None


def create_application(
    cursor, payload: PatientApplicationCreate, actor_id: str
) -> PatientApplication:
    application_id = str(uuid.uuid4())

    fields = {
        "id": application_id,
        "patient_id": payload.patient_id,
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
        "status_reason": None,
        "assigned_to_id": payload.assigned_to_id,
        "original_file_path": payload.original_file_path,
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
        assigned_to_id=payload.assigned_to_id,
    )
    return get_application_or_404(cursor, application_id)


def update_application(
    cursor, application_id: str, payload: PatientApplicationUpdate, actor_id: str
) -> PatientApplication:
    existing = get_application_or_404(cursor, application_id)

    fields = payload.model_dump(exclude_unset=True)

    fields["updated_by_id"] = actor_id
    fields["updated_at"] = NOW

    status = fields.get("status")
    if status == "submitted" and existing.status != "submitted":
        fields["submitted_by_id"] = actor_id
        fields["submitted_at"] = NOW
    elif status in ("approved", "rejected"):
        # Not conditional on the status changing: rejecting an
        # already-rejected application is a second verdict, by whoever
        # gave it, and the record has to move on to that one.
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


