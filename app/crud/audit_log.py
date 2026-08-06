"""Audit log CRUD (append + read only -- audit rows are never mutated).

old_values/new_values are JSON serialised to STRING because ORC/Hive has
no native JSON type.
"""
import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from app.db import execute
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
    created_at = datetime.now(timezone.utc).replace(tzinfo=None)
    execute(
        cursor,
        f"INSERT INTO `audit_logs` ({_COLS}) "
        f"VALUES ({', '.join('%s' for _ in COLUMNS)})",
        (
            audit_id,
            payload.action,
            payload.entity_type,
            payload.entity_id,
            payload.user_id,
            dumps(payload.old_values),
            dumps(payload.new_values),
            created_at.strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    log.info(
        "audit_recorded",
        audit_id=audit_id,
        action=payload.action,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
    )
    return AuditLog(
        id=audit_id,
        action=payload.action,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        user_id=payload.user_id,
        old_values=payload.old_values,
        new_values=payload.new_values,
        created_at=created_at,
    )


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
    limit: int = 100,
) -> List[AuditLog]:
    where, params = [], []
    if entity_type:
        where.append("`entity_type` = %s")
        params.append(entity_type)
    if entity_id:
        where.append("`entity_id` = %s")
        params.append(entity_id)

    sql = f"SELECT {_COLS} FROM `audit_logs`"
    if where:
        sql += " WHERE " + " AND ".join(where)
    # limit is an int from a validated query param, not caller-controlled
    # text, so interpolating it is safe -- Hive rejects %s in LIMIT.
    sql += f" ORDER BY `created_at` DESC LIMIT {int(limit)}"

    execute(cursor, sql, tuple(params))
    return [_row_to_audit(r) for r in cursor.fetchall()]
