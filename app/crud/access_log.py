"""Reading the access trail. Append-only: there is no update or delete."""
from typing import List, Optional

from app.access_log import COLUMNS, PARTITION_COLUMN
from app.db import execute
from app.logging_setup import get_logger
from app.schemas import AccessLog

log = get_logger(__name__)

_COLS = ", ".join(f"`{c}`" for c in COLUMNS)

MAX_LIMIT = 1000


def _row_to_access(row) -> AccessLog:
    values = dict(zip(COLUMNS, row))
    values["identified"] = (
        None if values["identified"] is None else bool(values["identified"])
    )
    return AccessLog(**values)


def list_access_logs(
    cursor,
    actor_id: Optional[str] = None,
    actor_username: Optional[str] = None,
    patient_id: Optional[str] = None,
    resource_id: Optional[str] = None,
    action: Optional[str] = None,
    outcome: Optional[str] = None,
    identified_only: bool = False,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 100,
) -> List[AccessLog]:
    """Filtered access events, newest first.

    The date bounds are applied to the partition column, not to
    `occurred_at`, so a bounded query reads only the days it needs
    instead of scanning every day ever written.
    """
    where, params = [], []

    if date_from:
        where.append(f"`{PARTITION_COLUMN}` >= %s")
        params.append(date_from)
    if date_to:
        where.append(f"`{PARTITION_COLUMN}` <= %s")
        params.append(date_to)

    for column, value in (
        ("actor_id", actor_id),
        ("actor_username", actor_username),
        ("patient_id", patient_id),
        ("resource_id", resource_id),
        ("action", action),
        ("outcome", outcome),
    ):
        if value:
            where.append(f"`{column}` = %s")
            params.append(value)

    if identified_only:
        where.append("`identified` = TRUE")

    sql = f"SELECT {_COLS} FROM `access_logs`"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += f" ORDER BY `occurred_at` DESC LIMIT {int(min(limit, MAX_LIMIT))}"

    execute(cursor, sql, tuple(params))
    return [_row_to_access(row) for row in cursor.fetchall()]


def count_by_actor(
    cursor,
    action: str,
    date_from: str,
    since,
    outcome: Optional[str] = None,
    identified_only: bool = False,
) -> List[tuple]:
    """(actor, count) for one action since a moment, busiest first.

    What the alerting job asks: who has done a lot of this lately.
    """
    where = [f"`{PARTITION_COLUMN}` >= %s", "`action` = %s", "`occurred_at` >= %s"]
    params = [date_from, action, since]

    if outcome:
        where.append("`outcome` = %s")
        params.append(outcome)
    if identified_only:
        where.append("`identified` = TRUE")

    execute(
        cursor,
        "SELECT `actor_username`, `actor_id`, COUNT(*) AS hits, "
        "COUNT(DISTINCT `patient_id`) AS patients "
        f"FROM `access_logs` WHERE {' AND '.join(where)} "
        "GROUP BY `actor_username`, `actor_id` ORDER BY hits DESC",
        tuple(params),
    )
    return list(cursor.fetchall())
