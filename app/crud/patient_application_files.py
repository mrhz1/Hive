"""Application document CRUD, against `patient_application_files`."""
import uuid
from typing import List, Optional

from app.db import NOW_SQL, authoritative, execute
from app.errors import NotFoundError
from app.logging_setup import get_logger
from app.schemas import PatientApplicationFile, PatientApplicationFileUpdate

log = get_logger(__name__)

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
    "review_status",
    "review_note",
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
    """Records an uploaded document."""
    new_id = file_id or str(uuid.uuid4())

    placeholders = ", ".join(
        NOW_SQL if c == "created_at" else "%s" for c in COLUMNS
    )
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
            False,  # is_deidentified
            # created_at is inlined above, not bound here.
            description,
            file_path,
            None,  # de_identified_file_path
            "pending",  # review_status -- nobody has looked at it yet
            None,  # review_note
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


def oldest_with_status(cursor, deid_status: str) -> Optional[PatientApplicationFile]:
    """The longest-waiting file in one de-identification state.

    Asked of the database rather than answered in Python. The dispatcher
    runs this on every pass, and reading every document row ever stored
    in order to find the one that has waited longest is a table scan for
    a single row -- which is most of the delay between clicking
    de-identify and the job actually starting.
    """
    execute(
        cursor,
        f"SELECT {_COLS} FROM `patient_application_files` "
        "WHERE `deid_status` = %s ORDER BY `created_at` ASC LIMIT 1",
        (deid_status,),
    )
    row = cursor.fetchone()
    return _row_to_file(row) if row else None


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
        # A miss may only mean the query engine has not caught up with a
        # row written a moment ago. Ask the engine that owns it first.
        with authoritative(cursor):
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


def update_files(
    cursor, file_ids: List[str], payload: PatientApplicationFileUpdate
) -> int:
    """Set the same fields on many files, in one statement.

    The bulk endpoints used to call update_file in a loop, which is three
    statements each -- an existence check, the UPDATE, and a read-back
    for the return value. On an application holding a thousand documents
    that is three thousand statements, every UPDATE of them a Hive ACID
    delta write costing seconds. One statement does the same work.

    Returns how many ids were asked for. Nothing is read back: the
    callers report counts, not rows, and the count is known before the
    write from the list they already hold.
    """
    if not file_ids:
        return 0

    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        return 0

    set_clause = ", ".join(f"`{col}` = %s" for col in fields)
    placeholders = ", ".join("%s" for _ in file_ids)
    execute(
        cursor,
        f"UPDATE `patient_application_files` SET {set_clause} "
        f"WHERE `id` IN ({placeholders})",
        tuple(fields.values()) + tuple(file_ids),
    )
    # One line for the batch rather than one per file, but carrying the
    # ids, so the trail still says exactly which rows moved.
    log.info(
        "application_files_updated",
        count=len(file_ids),
        fields=sorted(fields),
        file_ids=file_ids,
    )
    return len(file_ids)


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
    """Used when an application is removed, so its documents do not linger as unreachable rows and orphaned bytes."""
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
