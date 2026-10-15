import uuid
from datetime import datetime, timezone
from typing import List, Optional

from app.db import NOW_SQL, execute
from app.errors import NotFoundError
from app.logging_setup import get_logger
from app.schemas import OriginalGrant

log = get_logger(__name__)

COLUMNS = (
    "id", "file_id", "user_id", "reason", "granted_by_id", "granted_at",
    "revoked_by_id", "revoked_at",
)
_COLS = ", ".join(f"`{c}`" for c in COLUMNS)


def _row(row) -> OriginalGrant:
    return OriginalGrant(**dict(zip(COLUMNS, row)))


def list_for_file(cursor, file_id: str) -> List[OriginalGrant]:
    execute(cursor, f"SELECT {_COLS} FROM `original_grants` WHERE `file_id` = %s", (file_id,))
    return sorted((_row(r) for r in cursor.fetchall()), key=lambda g: str(g.granted_at), reverse=True)


def active_for_user(cursor, user_id: str) -> List[OriginalGrant]:
    execute(cursor, f"SELECT {_COLS} FROM `original_grants` WHERE `user_id` = %s", (user_id,))
    return [g for g in (_row(r) for r in cursor.fetchall()) if not g.revoked_at]


def has_active(cursor, file_id: str, user_id: str) -> bool:
    execute(
        cursor,
        f"SELECT {_COLS} FROM `original_grants` WHERE `file_id` = %s AND `user_id` = %s",
        (file_id, user_id),
    )
    return any(not _row(r).revoked_at for r in cursor.fetchall())


def get_or_404(cursor, grant_id: str) -> OriginalGrant:
    execute(cursor, f"SELECT {_COLS} FROM `original_grants` WHERE `id` = %s", (grant_id,))
    row = cursor.fetchone()
    if not row:
        raise NotFoundError(f"Grant '{grant_id}' not found")
    return _row(row)


def create(cursor, file_id: str, user_id: str, reason: str, granted_by_id: str) -> OriginalGrant:
    grant_id = str(uuid.uuid4())
    execute(
        cursor,
        f"INSERT INTO `original_grants` ({_COLS}) "
        f"VALUES (%s, %s, %s, %s, %s, {NOW_SQL}, NULL, NULL)",
        (grant_id, file_id, user_id, reason, granted_by_id),
    )
    log.info("original_granted", grant_id=grant_id, file_id=file_id, user_id=user_id)
    return get_or_404(cursor, grant_id)


def revoke(cursor, grant_id: str, revoked_by_id: str, when: Optional[str] = None) -> OriginalGrant:
    moment = when or datetime.now(timezone.utc).isoformat(timespec="seconds")
    execute(
        cursor,
        "UPDATE `original_grants` SET `revoked_by_id` = %s, `revoked_at` = %s WHERE `id` = %s",
        (revoked_by_id, moment, grant_id),
    )
    log.info("original_grant_revoked", grant_id=grant_id)
    return get_or_404(cursor, grant_id)
