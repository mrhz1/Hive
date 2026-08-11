"""Audit log CRUD (append + read only -- audit rows are never mutated)."""
import json
import uuid
from typing import List, Optional

from app.db import NOW_SQL, execute
from app.errors import NotFoundError
from app.logging_setup import get_logger
from app.schemas import AuditLog, AuditLogCreate

log = get_logger(__name__)

# Order must match sql/schema.sql -- Hive INSERT is positional.
COLUMNS = (
    "id",
    "action",
    "entity_type",
    "entity_id",
    "user_id",
    "old_values",
    "new_values",
    "created_at",
)

_COLS = ", ".join(f"`{c}`" for c in COLUMNS)

_VALUES = ", ".join(NOW_SQL if c == "created_at" else "%s" for c in COLUMNS)


def dumps(value: Optional[dict]) -> Optional[str]:
    """JSON-encode for storage. default=str so datetimes survive."""
    if value is None:
        return None
    return json.dumps(value, default=str, sort_keys=True)


def _loads(raw) -> Optional[dict]:
    if raw is None:
        return None
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        log.warning("audit_values_parse_failed", raw=str(raw)[:200])
        return None
    return parsed if isinstance(parsed, dict) else None


def _row_to_audit(row) -> AuditLog:
    values = dict(zip(COLUMNS, row))
    values["old_values"] = _loads(values["old_values"])
    values["new_values"] = _loads(values["new_values"])
    return AuditLog(**values)


def create_audit_log(cursor, payload: AuditLogCreate) -> AuditLog:
    audit_id = str(uuid.uuid4())
    execute(
        cursor,
        f"INSERT INTO `audit_logs` ({_COLS}) VALUES ({_VALUES})",
        (
            audit_id,
            payload.action,
            payload.entity_type,
            payload.entity_id,
            payload.user_id,
            dumps(payload.old_values),
            dumps(payload.new_values),
        ),
    )
    log.info(
        "audit_recorded",
        audit_id=audit_id,
        action=payload.action,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
    )
    return get_audit_log(cursor, audit_id)


def get_audit_log(cursor, audit_id: str) -> AuditLog:
    execute(cursor, f"SELECT {_COLS} FROM `audit_logs` WHERE `id` = %s", (audit_id,))
    row = cursor.fetchone()
    if row is None:
        raise NotFoundError(f"Audit log '{audit_id}' not found")
    return _row_to_audit(row)


def list_audit_logs(
    cursor,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    user_id: Optional[str] = None,
    action: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 100,
) -> List[AuditLog]:
    """Filtered change events, newest first.

    `user_id` and the date bounds are what make this answer "what did
    this person do, and when" -- the question an access review and an
    incident both start from, and which this could not be asked before.
    """
    where, params = [], []
    if entity_type:
        where.append("`entity_type` = %s")
        params.append(entity_type)
    if entity_id:
        where.append("`entity_id` = %s")
        params.append(entity_id)
    if user_id:
        where.append("`user_id` = %s")
        params.append(user_id)
    if action:
        where.append("`action` = %s")
        params.append(action)
    if date_from:
        where.append("`created_at` >= %s")
        params.append(date_from)
    if date_to:
        # Inclusive of the whole day the caller named.
        where.append("`created_at` < %s")
        params.append(f"{date_to} 23:59:59.999")

    sql = f"SELECT {_COLS} FROM `audit_logs`"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += f" ORDER BY `created_at` DESC LIMIT {int(limit)}"

    execute(cursor, sql, tuple(params))
    return [_row_to_audit(r) for r in cursor.fetchall()]
