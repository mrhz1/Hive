"""Hive access for projects, their cohort/ID map and their releases."""

import secrets
import uuid
from typing import Any, List, Optional

from app.db import NOW_SQL, NULL_TIMESTAMP_SQL, execute
from app.errors import NotFoundError
from app.logging_setup import get_logger
from app.project_schemas import (
    Project,
    ProjectCreate,
    ProjectPatient,
    ProjectRelease,
    ProjectUpdate,
)

log = get_logger(__name__)

NOW = object()
NULL_TS = object()

# No 0/O or 1/I: the IDs are read and typed by people.
ID_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

# Five years either way, never zero: a shift of 0 would leave real dates.
MAX_SHIFT_DAYS = 1826

PROJECT_COLUMNS = (
    "id", "short_code", "name", "description", "approval_reference",
    "consent_confirmed", "documents_approved", "status", "status_reason",
    "created_by_id", "created_at", "updated_at",
)
PATIENT_COLUMNS = (
    "id", "project_id", "patient_id", "project_patient_id", "date_shift_days", "added_at",
)
RELEASE_COLUMNS = (
    "id", "project_id", "status", "status_reason", "prepared_by_id", "prepared_at",
    "reviewed_by_id", "reviewed_at", "patients", "applications", "documents",
    "files_included", "archive_path", "inbox_path", "release_path",
)


def _cols(columns) -> str:
    return ", ".join(f"`{c}`" for c in columns)


def _value_sql(value: Any) -> tuple:
    if value is NOW:
        return NOW_SQL, ()
    if value is NULL_TS:
        return NULL_TIMESTAMP_SQL, ()
    return "%s", (value,)


def _insert(cursor, table: str, columns, fields: dict) -> None:
    values, params = [], []
    for column in columns:
        sql, bound = _value_sql(fields.get(column))
        values.append(sql)
        params.extend(bound)
    execute(
        cursor,
        f"INSERT INTO `{table}` ({_cols(columns)}) VALUES ({', '.join(values)})",
        tuple(params),
    )


def _update(cursor, table: str, row_id: str, fields: dict) -> None:
    parts, params = [], []
    for column, value in fields.items():
        sql, bound = _value_sql(value)
        parts.append(f"`{column}` = {sql}")
        params.extend(bound)
    execute(
        cursor,
        f"UPDATE `{table}` SET {', '.join(parts)} WHERE `id` = %s",
        tuple(params) + (row_id,),
    )


def random_code(length: int) -> str:
    return "".join(secrets.choice(ID_ALPHABET) for _ in range(length))


def random_shift() -> int:
    shift = 0
    while shift == 0:
        shift = secrets.randbelow(2 * MAX_SHIFT_DAYS + 1) - MAX_SHIFT_DAYS
    return shift


# --- projects -----------------------------------------------------------


def _project(row) -> Project:
    values = dict(zip(PROJECT_COLUMNS, row))
    values["consent_confirmed"] = bool(values["consent_confirmed"])
    values["documents_approved"] = bool(values["documents_approved"])
    return Project(**values)


def list_projects(cursor) -> List[Project]:
    execute(
        cursor,
        f"SELECT {_cols(PROJECT_COLUMNS)} FROM `projects` ORDER BY `created_at` DESC",
    )
    return [_project(r) for r in cursor.fetchall()]


def get_project(cursor, project_id: str) -> Optional[Project]:
    execute(
        cursor,
        f"SELECT {_cols(PROJECT_COLUMNS)} FROM `projects` WHERE `id` = %s",
        (project_id,),
    )
    row = cursor.fetchone()
    return _project(row) if row else None


def get_project_or_404(cursor, project_id: str) -> Project:
    project = get_project(cursor, project_id)
    if project is None:
        raise NotFoundError(f"Project '{project_id}' not found")
    return project


def create_project(cursor, payload: ProjectCreate, actor_id: str) -> Project:
    project_id = str(uuid.uuid4())
    taken = {p.short_code for p in list_projects(cursor)}
    short_code = "P" + random_code(4)
    while short_code in taken:
        short_code = "P" + random_code(4)

    _insert(
        cursor,
        "projects",
        PROJECT_COLUMNS,
        {
            "id": project_id,
            "short_code": short_code,
            "name": payload.name,
            "description": payload.description,
            "approval_reference": payload.approval_reference,
            "consent_confirmed": payload.consent_confirmed,
            "documents_approved": payload.documents_approved,
            "status": "draft",
            "status_reason": None,
            "created_by_id": actor_id,
            "created_at": NOW,
            "updated_at": NOW,
        },
    )
    log.info("project_created", project_id=project_id, short_code=short_code)
    return get_project_or_404(cursor, project_id)


def update_project(cursor, project_id: str, payload: ProjectUpdate) -> Project:
    get_project_or_404(cursor, project_id)
    fields = payload.model_dump(exclude_unset=True)
    if "name" in fields and not (fields["name"] or "").strip():
        fields.pop("name")
    fields["updated_at"] = NOW
    _update(cursor, "projects", project_id, fields)
    return get_project_or_404(cursor, project_id)


def set_project_status(cursor, project_id: str, status: str, reason: Optional[str] = None) -> Project:
    _update(
        cursor,
        "projects",
        project_id,
        {"status": status, "status_reason": reason, "updated_at": NOW},
    )
    return get_project_or_404(cursor, project_id)


def delete_project(cursor, project_id: str) -> None:
    for member in list_cohort(cursor, project_id):
        execute(cursor, "DELETE FROM `project_patients` WHERE `id` = %s", (member.id,))
    execute(cursor, "DELETE FROM `projects` WHERE `id` = %s", (project_id,))
    log.info("project_deleted", project_id=project_id)


# --- cohort and ID map --------------------------------------------------


def _member(row) -> ProjectPatient:
    values = dict(zip(PATIENT_COLUMNS, row))
    values["date_shift_days"] = int(values["date_shift_days"] or 0)
    return ProjectPatient(**values)


def list_cohort(cursor, project_id: str) -> List[ProjectPatient]:
    execute(
        cursor,
        f"SELECT {_cols(PATIENT_COLUMNS)} FROM `project_patients` WHERE `project_id` = %s",
        (project_id,),
    )
    return sorted((_member(r) for r in cursor.fetchall()), key=lambda m: m.patient_id)


def set_cohort(cursor, project: Project, patient_ids: List[str]) -> List[ProjectPatient]:
    """Make the cohort exactly these patients.

    A patient already in it keeps their project ID and date shift, so a
    project prepared again stays consistent. A new one gets a fresh random
    ID and shift; one taken out loses theirs.
    """
    wanted = list(dict.fromkeys(patient_ids))
    current = {m.patient_id: m for m in list_cohort(cursor, project.id)}

    for patient_id, member in current.items():
        if patient_id not in wanted:
            execute(cursor, "DELETE FROM `project_patients` WHERE `id` = %s", (member.id,))

    taken = {m.project_patient_id for m in current.values()}
    for patient_id in wanted:
        if patient_id in current:
            continue
        project_patient_id = f"{project.short_code}-{random_code(6)}"
        while project_patient_id in taken:
            project_patient_id = f"{project.short_code}-{random_code(6)}"
        taken.add(project_patient_id)
        _insert(
            cursor,
            "project_patients",
            PATIENT_COLUMNS,
            {
                "id": str(uuid.uuid4()),
                "project_id": project.id,
                "patient_id": patient_id,
                "project_patient_id": project_patient_id,
                "date_shift_days": random_shift(),
                "added_at": NOW,
            },
        )
    log.info("project_cohort_set", project_id=project.id, patients=len(wanted))
    return list_cohort(cursor, project.id)


# --- releases -----------------------------------------------------------


def _release(row) -> ProjectRelease:
    values = dict(zip(RELEASE_COLUMNS, row))
    for count in ("patients", "applications", "documents"):
        values[count] = int(values[count] or 0)
    values["files_included"] = bool(values["files_included"])
    return ProjectRelease(**values)


def list_releases(cursor, project_id: Optional[str] = None, status: Optional[str] = None) -> List[ProjectRelease]:
    sql = f"SELECT {_cols(RELEASE_COLUMNS)} FROM `project_releases`"
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
    releases = [_release(r) for r in cursor.fetchall()]
    return sorted(releases, key=lambda r: str(r.prepared_at or ""), reverse=True)


def get_release_or_404(cursor, release_id: str) -> ProjectRelease:
    execute(
        cursor,
        f"SELECT {_cols(RELEASE_COLUMNS)} FROM `project_releases` WHERE `id` = %s",
        (release_id,),
    )
    row = cursor.fetchone()
    if row is None:
        raise NotFoundError(f"Release '{release_id}' not found")
    return _release(row)


def create_release(cursor, release_id: str, project_id: str, actor_id: str, counts: dict, paths: dict, files_included: bool) -> ProjectRelease:
    _insert(
        cursor,
        "project_releases",
        RELEASE_COLUMNS,
        {
            "id": release_id,
            "project_id": project_id,
            "status": "in_review",
            "status_reason": None,
            "prepared_by_id": actor_id,
            "prepared_at": NOW,
            "reviewed_by_id": None,
            "reviewed_at": NULL_TS,
            "patients": counts["patients"],
            "applications": counts["applications"],
            "documents": counts["documents"],
            "files_included": files_included,
            "archive_path": paths["archive"],
            "inbox_path": paths["inbox"],
            "release_path": None,
        },
    )
    return get_release_or_404(cursor, release_id)


def decide_release(cursor, release_id: str, status: str, actor_id: str, reason: Optional[str] = None, release_path: Optional[str] = None) -> ProjectRelease:
    fields = {
        "status": status,
        "status_reason": reason,
        "reviewed_by_id": actor_id,
        "reviewed_at": NOW,
    }
    if release_path is not None:
        fields["release_path"] = release_path
    _update(cursor, "project_releases", release_id, fields)
    return get_release_or_404(cursor, release_id)
