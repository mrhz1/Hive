import json
import uuid
from typing import Any, List

from app.db import NOW_SQL, execute
from app.errors import NotFoundError
from app.logging_setup import get_logger
from app.schemas import AbstractionFolder

log = get_logger(__name__)

NOW = object()

COLUMNS = (
    "id", "name", "purpose", "owner_id", "status", "criteria", "file_ids",
    "file_count", "folder_path", "created_at", "expires_at", "deleted_at",
    "deleted_by_id", "deleted_reason", "assigned_to_id",
)
_COLS = ", ".join(f"`{c}`" for c in COLUMNS)


def _value_sql(value: Any) -> tuple:
    if value is NOW:
        return NOW_SQL, ()
    return "%s", (value,)


def _row(row) -> AbstractionFolder:
    values = dict(zip(COLUMNS, row))
    values.pop("file_ids", None)
    values["file_count"] = int(values.get("file_count") or 0)
    return AbstractionFolder(**values)


def list_folders(cursor) -> List[AbstractionFolder]:
    execute(cursor, f"SELECT {_COLS} FROM `abstraction_folders` ORDER BY `created_at` DESC")
    return [_row(r) for r in cursor.fetchall()]


def get_folder_or_404(cursor, folder_id: str) -> AbstractionFolder:
    execute(cursor, f"SELECT {_COLS} FROM `abstraction_folders` WHERE `id` = %s", (folder_id,))
    row = cursor.fetchone()
    if not row:
        raise NotFoundError(f"Abstraction folder '{folder_id}' not found")
    return _row(row)


def file_ids(cursor, folder_id: str) -> List[str]:
    execute(cursor, "SELECT `file_ids` FROM `abstraction_folders` WHERE `id` = %s", (folder_id,))
    row = cursor.fetchone()
    if not row or not row[0]:
        return []
    try:
        return list(json.loads(row[0]))
    except ValueError:
        return []


def create_folder(cursor, fields: dict) -> AbstractionFolder:
    folder_id = fields.get("id") or str(uuid.uuid4())
    values = dict(fields, id=folder_id, created_at=NOW)
    sql_values, params = [], []
    for column in COLUMNS:
        sql, bound = _value_sql(values.get(column))
        sql_values.append(sql)
        params.extend(bound)
    execute(
        cursor,
        f"INSERT INTO `abstraction_folders` ({_COLS}) VALUES ({', '.join(sql_values)})",
        tuple(params),
    )
    log.info("abstraction_folder_created", folder_id=folder_id, files=values.get("file_count"))
    return get_folder_or_404(cursor, folder_id)


def update_folder(cursor, folder_id: str, fields: dict) -> AbstractionFolder:
    parts, params = [], []
    for column, value in fields.items():
        sql, bound = _value_sql(value)
        parts.append(f"`{column}` = {sql}")
        params.extend(bound)
    execute(
        cursor,
        f"UPDATE `abstraction_folders` SET {', '.join(parts)} WHERE `id` = %s",
        tuple(params) + (folder_id,),
    )
    log.info("abstraction_folder_updated", folder_id=folder_id, fields=sorted(fields))
    return get_folder_or_404(cursor, folder_id)
