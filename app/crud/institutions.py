from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.db import execute
from app.logging_setup import get_logger

log = get_logger(__name__)

COLUMNS = ("code", "name", "contact_email", "updated_by_id", "updated_at")
_COLS = ", ".join(f"`{c}`" for c in COLUMNS)


def normalise(code: Optional[str]) -> str:
    return (code or "").strip().upper()


def _row(row) -> dict:
    return dict(zip(COLUMNS, row))


def list_institutions(cursor) -> List[dict]:
    execute(cursor, f"SELECT {_COLS} FROM `institutions`")
    return [_row(r) for r in cursor.fetchall()]


def get(cursor, code: str) -> Optional[dict]:
    execute(cursor, f"SELECT {_COLS} FROM `institutions` WHERE `code` = %s", (normalise(code),))
    row = cursor.fetchone()
    return _row(row) if row else None


def patient_counts(cursor) -> Dict[str, int]:
    execute(cursor, "SELECT `instcode`, COUNT(*) FROM `patient` GROUP BY `instcode`")
    out: Dict[str, int] = {}
    for code, count in cursor.fetchall():
        key = normalise(code)
        if key:
            out[key] = out.get(key, 0) + int(count or 0)
    return out


def save(cursor, code: str, name: Optional[str], contact_email: Optional[str], actor_id: str) -> dict:
    code = normalise(code)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if get(cursor, code):
        execute(
            cursor,
            "UPDATE `institutions` SET `name` = %s, `contact_email` = %s, "
            "`updated_by_id` = %s, `updated_at` = %s WHERE `code` = %s",
            (name, contact_email, actor_id, now, code),
        )
    else:
        execute(
            cursor,
            f"INSERT INTO `institutions` ({_COLS}) VALUES (%s, %s, %s, %s, %s)",
            (code, name, contact_email, actor_id, now),
        )
    log.info("institution_saved", code=code)
    return get(cursor, code) or {}


def delete(cursor, code: str) -> None:
    execute(cursor, "DELETE FROM `institutions` WHERE `code` = %s", (normalise(code),))
    log.info("institution_deleted", code=normalise(code))
