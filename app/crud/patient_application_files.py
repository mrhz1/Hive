"""Application document CRUD, against `patient_application_files`.

Documents belong to an application, not to a patient directly -- a
patient's files are reached through their applications. There is no
per-file review verdict here: approval is recorded once, on the
application row.

HiveQL only: %s paramstyle, backtick identifiers, STRING types, no
RETURNING/ON CONFLICT/sequences.
"""
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from app.db import execute
from app.errors import NotFoundError
from app.logging_setup import get_logger
from app.schemas import PatientApplicationFile, PatientApplicationFileUpdate

log = get_logger(__name__)

# Column order is the single source of truth for SELECT/INSERT and for
# mapping a row back onto the model -- adding a column means adding it
# here (and to sql/schema.sql) and nowhere else.
#
# Note the two spellings: `deidentified_file_name` against
# `de_identified_file_path`. That is what the Cloudera metastore has.
COLUMNS = (
    "id",
    "application_id",
    "original_file_name",
    "sanitized_file_name",
    "deidentified_file_name",
    "file_extension",
    "mime_type",
    "file_size",
    "deid_status",
    "is_deidentified",
    "created_at",
    "description",
    "file_path",
    "de_identified_file_path",
)

_COLS = ", ".join(f"`{c}`" for c in COLUMNS)


def _row_to_file(row) -> PatientApplicationFile:
    values = dict(zip(COLUMNS, row))
    values["file_size"] = int(values["file_size"] or 0)
    values["is_deidentified"] = bool(values["is_deidentified"])
    return PatientApplicationFile(**values)


def create_file(
    cursor,
    *,
    application_id: str,
    original_file_name: str,
    sanitized_file_name: str,
    file_extension: str,
    mime_type: str,
    file_size: int,
    file_path: str,
    description: Optional[str] = None,
    file_id: Optional[str] = None,
) -> PatientApplicationFile:
    """Records an uploaded document.

    Freshly uploaded files are 'pending' and not yet de-identified:
    nothing has been redacted, and claiming otherwise would be a privacy
    lie.
    """
    new_id = file_id or str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).replace(tzinfo=None)

    placeholders = ", ".join("%s" for _ in COLUMNS)
    execute(
        cursor,
        f"INSERT INTO `patient_application_files` ({_COLS}) "
        f"VALUES ({placeholders})",
        (
            new_id,
            application_id,
            original_file_name,
            sanitized_file_name,
            None,  # deidentified_file_name
            file_extension,
            mime_type,
            file_size,
            "pending",
            # A freshly uploaded file has not been through the OCR job,
            # so it is not de-identified until that job says otherwise.
            False,  # is_deidentified
            created_at.strftime("%Y-%m-%d %H:%M:%S"),
            description,
            file_path,
            None,  # de_identified_file_path
        ),
    )
    log.info(
        "application_file_created",
        file_id=new_id,
        application_id=application_id,
        name=sanitized_file_name,
        bytes=file_size,
    )
    return get_file_or_404(cursor, new_id)


def list_files(
    cursor, application_id: Optional[str] = None
) -> List[PatientApplicationFile]:
    sql = f"SELECT {_COLS} FROM `patient_application_files`"
    params: tuple = ()
    if application_id:
        sql += " WHERE `application_id` = %s"
        params = (application_id,)
    sql += " ORDER BY `created_at` DESC"

    execute(cursor, sql, params)
    return [_row_to_file(r) for r in cursor.fetchall()]


def get_file(cursor, file_id: str) -> Optional[PatientApplicationFile]:
    execute(
        cursor,
        f"SELECT {_COLS} FROM `patient_application_files` WHERE `id` = %s",
        (file_id,),
    )
    row = cursor.fetchone()
    return _row_to_file(row) if row else None


def get_file_or_404(cursor, file_id: str) -> PatientApplicationFile:
    found = get_file(cursor, file_id)
    if found is None:
        raise NotFoundError(f"File '{file_id}' not found")
    return found


def update_file(
    cursor, file_id: str, payload: PatientApplicationFileUpdate
) -> PatientApplicationFile:
    get_file_or_404(cursor, file_id)

    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        return get_file_or_404(cursor, file_id)

    set_clause = ", ".join(f"`{col}` = %s" for col in fields)
    params = tuple(fields.values()) + (file_id,)
    execute(
        cursor,
        f"UPDATE `patient_application_files` SET {set_clause} WHERE `id` = %s",
        params,
    )
    log.info("application_file_updated", file_id=file_id, fields=sorted(fields))
    return get_file_or_404(cursor, file_id)


def delete_file(cursor, file_id: str) -> PatientApplicationFile:
    existing = get_file_or_404(cursor, file_id)
    execute(
        cursor, "DELETE FROM `patient_application_files` WHERE `id` = %s", (file_id,)
    )
    log.info("application_file_deleted", file_id=file_id)
    return existing


def delete_files_for_application(
    cursor, application_id: str
) -> List[PatientApplicationFile]:
    """Used when an application is removed, so its documents do not linger
    as unreachable rows and orphaned bytes."""
    existing = list_files(cursor, application_id)
    if existing:
        execute(
            cursor,
            "DELETE FROM `patient_application_files` WHERE `application_id` = %s",
            (application_id,),
        )
        log.info(
            "application_files_deleted",
            application_id=application_id,
            count=len(existing),
        )
    return existing
