"""Customer file metadata CRUD. HiveQL only: %s paramstyle, backtick
identifiers, STRING types, no RETURNING/ON CONFLICT/sequences.
"""
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from app.db import execute
from app.errors import NotFoundError
from app.logging_setup import get_logger
from app.schemas import CustomerFile, CustomerFileUpdate

log = get_logger(__name__)

_COLS = (
    "`id`, `customer_id`, `original_file_name`, `sanitized_file_name`, "
    "`deidentified_file_name`, `file_extension`, `mime_type`, `file_size`, "
    "`deid_status`, `is_identified`, `created_at`, `description`, "
    "`file_path`, `deidentified_file_path`"
)


def _row_to_file(row) -> CustomerFile:
    return CustomerFile(
        id=row[0],
        customer_id=row[1],
        original_file_name=row[2],
        sanitized_file_name=row[3],
        deidentified_file_name=row[4],
        file_extension=row[5],
        mime_type=row[6],
        file_size=int(row[7]) if row[7] is not None else 0,
        deid_status=row[8],
        is_identified=bool(row[9]),
        created_at=row[10],
        description=row[11],
        file_path=row[12],
        deidentified_file_path=row[13],
    )


def create_file(
    cursor,
    *,
    customer_id: str,
    original_file_name: str,
    sanitized_file_name: str,
    file_extension: str,
    mime_type: str,
    file_size: int,
    file_path: str,
    description: Optional[str] = None,
    file_id: Optional[str] = None,
) -> CustomerFile:
    """Records an uploaded document.

    Freshly uploaded files are 'pending' and still identified: nothing has
    been de-identified yet, and claiming otherwise would be a privacy lie.
    """
    new_id = file_id or str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).replace(tzinfo=None)

    execute(
        cursor,
        f"INSERT INTO `customer_files` ({_COLS}) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            new_id,
            customer_id,
            original_file_name,
            sanitized_file_name,
            None,  # deidentified_file_name
            file_extension,
            mime_type,
            file_size,
            "pending",
            True,  # is_identified
            created_at.strftime("%Y-%m-%d %H:%M:%S"),
            description,
            file_path,
            None,  # deidentified_file_path
        ),
    )
    log.info(
        "customer_file_created",
        file_id=new_id,
        customer_id=customer_id,
        name=sanitized_file_name,
        bytes=file_size,
    )
    return get_file_or_404(cursor, new_id)


def list_files(cursor, customer_id: Optional[str] = None) -> List[CustomerFile]:
    sql = f"SELECT {_COLS} FROM `customer_files`"
    params: tuple = ()
    if customer_id:
        sql += " WHERE `customer_id` = %s"
        params = (customer_id,)
    sql += " ORDER BY `created_at` DESC"

    execute(cursor, sql, params)
    return [_row_to_file(r) for r in cursor.fetchall()]


def get_file(cursor, file_id: str) -> Optional[CustomerFile]:
    execute(cursor, f"SELECT {_COLS} FROM `customer_files` WHERE `id` = %s", (file_id,))
    row = cursor.fetchone()
    return _row_to_file(row) if row else None


def get_file_or_404(cursor, file_id: str) -> CustomerFile:
    found = get_file(cursor, file_id)
    if found is None:
        raise NotFoundError(f"File '{file_id}' not found")
    return found


def update_file(cursor, file_id: str, payload: CustomerFileUpdate) -> CustomerFile:
    get_file_or_404(cursor, file_id)

    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        return get_file_or_404(cursor, file_id)

    set_clause = ", ".join(f"`{col}` = %s" for col in fields)
    params = tuple(fields.values()) + (file_id,)
    execute(cursor, f"UPDATE `customer_files` SET {set_clause} WHERE `id` = %s", params)
    log.info("customer_file_updated", file_id=file_id, fields=sorted(fields))
    return get_file_or_404(cursor, file_id)


def delete_file(cursor, file_id: str) -> CustomerFile:
    existing = get_file_or_404(cursor, file_id)
    execute(cursor, "DELETE FROM `customer_files` WHERE `id` = %s", (file_id,))
    log.info("customer_file_deleted", file_id=file_id)
    return existing


def delete_files_for_customer(cursor, customer_id: str) -> List[CustomerFile]:
    """Used when a customer is removed, so their documents do not linger
    as unreachable rows and orphaned bytes."""
    existing = list_files(cursor, customer_id)
    if existing:
        execute(
            cursor,
            "DELETE FROM `customer_files` WHERE `customer_id` = %s",
            (customer_id,),
        )
        log.info(
            "customer_files_deleted", customer_id=customer_id, count=len(existing)
        )
    return existing
