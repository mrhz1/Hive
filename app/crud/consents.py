"""Hive access for the patient consent matrix (one row per recorded decision)."""

import uuid
from datetime import date, datetime, timezone
from typing import List, Optional

from app.db import execute
from app.logging_setup import get_logger
from app.project_schemas import Consent, ConsentCreate

log = get_logger(__name__)

COLUMNS = (
    "id", "patient_id", "consent_type", "status", "version", "consent_date",
    "note", "source", "recorded_by_id", "recorded_at",
)
_COLS = ", ".join(f"`{c}`" for c in COLUMNS)


def _row(row) -> Consent:
    values = dict(zip(COLUMNS, row))
    day = values.get("consent_date")
    if isinstance(day, datetime):
        values["consent_date"] = day.date()
    elif isinstance(day, str):
        values["consent_date"] = date.fromisoformat(day[:10]) if day.strip() else None
    return Consent(**values)


def list_consents(cursor, patient_id: Optional[str] = None) -> List[Consent]:
    sql = f"SELECT {_COLS} FROM `patient_consents`"
    params: tuple = ()
    if patient_id:
        sql += " WHERE `patient_id` = %s"
        params = (patient_id,)
    execute(cursor, sql, params)
    return [_row(r) for r in cursor.fetchall()]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def insert_many(
    cursor, entries: List[ConsentCreate], source: str, actor_id: Optional[str]
) -> List[Consent]:
    """Record decisions; nothing is changed or deleted, so the history stays."""
    recorded_at = _now()
    rows = []
    for entry in entries:
        rows.append(
            {
                **entry.model_dump(),
                "id": str(uuid.uuid4()),
                "consent_date": entry.consent_date.isoformat() if entry.consent_date else None,
                "source": source,
                "recorded_by_id": actor_id,
                "recorded_at": recorded_at,
            }
        )
    placeholders = "(" + ", ".join(["%s"] * len(COLUMNS)) + ")"
    for start in range(0, len(rows), 200):
        part = rows[start : start + 200]
        execute(
            cursor,
            f"INSERT INTO `patient_consents` ({_COLS}) VALUES "
            + ", ".join([placeholders] * len(part)),
            tuple(row[c] for row in part for c in COLUMNS),
        )
    log.info("consents_recorded", count=len(rows), source=source)
    return [Consent(**{**row, "consent_date": entry.consent_date}) for row, entry in zip(rows, entries)]
