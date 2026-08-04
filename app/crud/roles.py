"""Role CRUD. HiveQL only: %s paramstyle, backtick identifiers, STRING
types, no RETURNING/ON CONFLICT/sequences.
"""
import json
import uuid
from typing import List, Optional

from app.db import execute
from app.errors import ConflictError, NotFoundError
from app.logging_setup import get_logger
from app.schemas import Role, RoleCreate, RoleUpdate

log = get_logger(__name__)

_COLS = "`id`, `name`, `permissions`"


def _parse_permissions(raw) -> List[str]:
    """impyla returns ARRAY<STRING> as bytes holding a JSON array, e.g.
    b'["users:read","users:create"]' -- not a Python list. Decode it."""
    if raw is None:
        return []
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("permissions_parse_failed", raw=raw[:200])
            return []
        return [str(p) for p in parsed] if isinstance(parsed, list) else []
    if isinstance(raw, list):
        return [str(p) for p in raw]
    return []


def _row_to_role(row) -> Role:
    return Role(id=row[0], name=row[1], permissions=_parse_permissions(row[2]))


def _array_literal(permissions: List[str]) -> tuple:
    """Hive rejects a bound parameter for a whole ARRAY column, so the
    array() call is built with one placeholder per element. Values stay
    parameterised -- only the arity is interpolated."""
    if not permissions:
        return "array()", ()
    placeholders = ", ".join(["%s"] * len(permissions))
    return f"array({placeholders})", tuple(permissions)


def get_role(cursor, role_id: str) -> Optional[Role]:
    execute(cursor, f"SELECT {_COLS} FROM `roles` WHERE `id` = %s", (role_id,))
    row = cursor.fetchone()
    return _row_to_role(row) if row else None


def get_role_by_name(cursor, name: str) -> Optional[Role]:
    execute(cursor, f"SELECT {_COLS} FROM `roles` WHERE `name` = %s", (name,))
    row = cursor.fetchone()
    return _row_to_role(row) if row else None


def list_roles(cursor) -> List[Role]:
    execute(cursor, f"SELECT {_COLS} FROM `roles`")
    return [_row_to_role(r) for r in cursor.fetchall()]


def create_role(cursor, payload: RoleCreate) -> Role:
    # Hive has no UNIQUE constraint, so uniqueness is a pre-check SELECT.
    # This is read-then-write, not atomic: two concurrent creates of the
    # same name can both pass. Acceptable here; a real fix needs an
    # external lock or a dedup pass.
    if get_role_by_name(cursor, payload.name) is not None:
        raise ConflictError(f"Role with name '{payload.name}' already exists")

    role_id = str(uuid.uuid4())
    arr_sql, arr_params = _array_literal(payload.permissions)
    execute(
        cursor,
        f"INSERT INTO `roles` ({_COLS}) SELECT %s, %s, {arr_sql}",
        (role_id, payload.name) + arr_params,
    )
    log.info("role_created", role_id=role_id, name=payload.name)
    return Role(id=role_id, name=payload.name, permissions=payload.permissions)


def update_role(cursor, role_id: str, payload: RoleUpdate) -> Role:
    existing = get_role(cursor, role_id)
    if existing is None:
        raise NotFoundError(f"Role '{role_id}' not found")

    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        return existing

    if "name" in fields and fields["name"] != existing.name:
        clash = get_role_by_name(cursor, fields["name"])
        if clash is not None and clash.id != role_id:
            raise ConflictError(f"Role with name '{fields['name']}' already exists")

    set_parts, params = [], []
    if "name" in fields:
        set_parts.append("`name` = %s")
        params.append(fields["name"])
    if "permissions" in fields:
        arr_sql, arr_params = _array_literal(fields["permissions"] or [])
        set_parts.append(f"`permissions` = {arr_sql}")
        params.extend(arr_params)

    params.append(role_id)
    execute(
        cursor,
        f"UPDATE `roles` SET {', '.join(set_parts)} WHERE `id` = %s",
        tuple(params),
    )
    log.info("role_updated", role_id=role_id, fields=sorted(fields))
    return get_role(cursor, role_id)


def delete_role(cursor, role_id: str) -> None:
    if get_role(cursor, role_id) is None:
        raise NotFoundError(f"Role '{role_id}' not found")
    execute(cursor, "DELETE FROM `roles` WHERE `id` = %s", (role_id,))
    log.info("role_deleted", role_id=role_id)
