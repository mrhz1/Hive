import json
import uuid
from typing import List, Optional

from app.crud.projects import NOW, _cols, _insert, _update
from app.db import execute
from app.errors import NotFoundError
from app.project_schemas import CaiProject

ACTIVE = "active"
ENDED = "ended"

COLUMNS = (
    "id", "project_id", "user_id", "cai_username", "release_id", "cai_project_id",
    "slug", "url", "files", "status", "created_by_id", "created_at", "expires_at",
    "ended_at", "ended_by_id", "ended_reason",
)


def _row(row) -> CaiProject:
    values = dict(zip(COLUMNS, row))
    try:
        values["files"] = json.loads(values["files"] or "[]")
    except ValueError:
        values["files"] = []
    return CaiProject(**values)


def list_cai_projects(
    cursor, project_id: Optional[str] = None, status: Optional[str] = None
) -> List[CaiProject]:
    sql = f"SELECT {_cols(COLUMNS)} FROM `cai_projects`"
    clauses, params = [], []
    if project_id:
        clauses.append("`project_id` = %s")
        params.append(project_id)
    if status:
        clauses.append("`status` = %s")
        params.append(status)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    execute(cursor, sql, tuple(params))
    found = [_row(r) for r in cursor.fetchall()]
    return sorted(found, key=lambda c: str(c.created_at or ""), reverse=True)


def get_or_404(cursor, record_id: str) -> CaiProject:
    execute(cursor, f"SELECT {_cols(COLUMNS)} FROM `cai_projects` WHERE `id` = %s", (record_id,))
    row = cursor.fetchone()
    if row is None:
        raise NotFoundError(f"Researcher project '{record_id}' not found")
    return _row(row)


def create(cursor, fields: dict) -> CaiProject:
    values = dict(fields)
    values["id"] = str(uuid.uuid4())
    values["files"] = json.dumps(values.get("files") or [])
    values["status"] = ACTIVE
    values["created_at"] = NOW
    _insert(cursor, "cai_projects", COLUMNS, values)
    return get_or_404(cursor, values["id"])


def update(cursor, record_id: str, fields: dict) -> CaiProject:
    _update(cursor, "cai_projects", record_id, fields)
    return get_or_404(cursor, record_id)
