"""Hive's rules around researcher projects in Cloudera AI.

A researcher project belongs to one Hive project member and holds only that
project's approved Zone 2 release, laid out in staging as
``<project code>/<release id>/``. Access lasts CAI_ACCESS_DAYS (default 182,
the protocol's 6 months) unless extended; at expiry, or when the Hive project
ends, the CAI project is deleted.

The approved release folder (ZONE2_DIR/<project code>/<release id>/) is
copied to staging at that same path by the API itself: in the background
right after approval, and again (missing files only) before each researcher
project is made, so nobody copies files by hand.
"""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from app import cai_provisioning as cai
from app.crud import cai_projects as crud
from app.crud import projects as projects_crud
from app.crud import users as users_crud
from app.errors import ConflictError, ValidationError
from app.logging_setup import get_logger
from app.project_schemas import CaiProject, CaiProvision

log = get_logger(__name__)

ENDED_PROJECT = "ended"


def access_days() -> int:
    try:
        return max(1, int(os.environ.get("CAI_ACCESS_DAYS", "182")))
    except ValueError:
        return 182


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def _parse(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def release_folder(short_code: str, release_id: str) -> str:
    return f"{short_code}/{release_id}"


def _latest_approved(cursor, project_id: str):
    approved = projects_crud.list_releases(cursor, project_id, status="approved")
    approved.sort(key=lambda r: str(r.reviewed_at or r.prepared_at or ""), reverse=True)
    return approved[0] if approved else None


def _with_names(cursor, records: List[CaiProject]) -> List[CaiProject]:
    names = {u.id: u.username for u in users_crud.list_users(cursor)}
    for record in records:
        record.username = names.get(record.user_id)
    return records


def list_for(cursor, project_id: Optional[str] = None, status: Optional[str] = None) -> List[CaiProject]:
    return _with_names(cursor, crud.list_cai_projects(cursor, project_id, status))


def provision(cursor, payload: CaiProvision, actor_id: str) -> CaiProject:
    project = projects_crud.get_project_or_404(cursor, payload.project_id)
    if project.status == ENDED_PROJECT:
        raise ValidationError("This project has ended")
    person = users_crud.get_user_or_404(cursor, payload.user_id)
    if not person.is_active:
        raise ValidationError(f"'{person.username}' is not active")
    if not projects_crud.is_member(cursor, project.id, person.id):
        raise ValidationError(f"'{person.username}' is not a member of this project")
    if any(c.user_id == person.id for c in crud.list_cai_projects(cursor, project.id, crud.ACTIVE)):
        raise ConflictError(
            f"'{person.username}' already has a Cloudera AI project for this project; "
            "remove it first to make a new one"
        )

    if payload.release_id:
        release = projects_crud.get_release_or_404(cursor, payload.release_id)
        if release.project_id != project.id:
            raise ValidationError("That release belongs to another project")
    else:
        release = _latest_approved(cursor, project.id)
        if release is None:
            raise ValidationError("The project has no approved Zone 2 release yet")
    if release.status != "approved":
        raise ValidationError(f"Release {release.id} is '{release.status}', not approved")

    own = release_folder(project.short_code, release.id)
    keep = cai.clean_keep_paths(payload.keep_paths or [own])
    outside = [k for k in keep if not (k == own or k.startswith(own + "/"))]
    if outside:
        raise ValidationError(
            f"Only files of release {release.id} ({own}/) can be given out: " + ", ".join(outside[:10])
        )

    cai_username = (payload.cai_username or person.username or "").strip()
    try:
        # Make sure staging holds the whole release first; only missing files are sent.
        push_release(project.short_code, release.id, release.release_path)
        result = cai.provision_researcher(
            cai_username,
            f"{project.short_code} {cai_username}",
            keep,
            description=f"Hive project {project.short_code}, release {release.id}",
        )
    except cai.ProvisioningError as exc:
        raise ValidationError(str(exc)) from exc

    record = crud.create(
        cursor,
        {
            "project_id": project.id,
            "user_id": person.id,
            "cai_username": cai_username,
            "release_id": release.id,
            "cai_project_id": result["project_id"],
            "slug": result["slug"],
            "url": result["url"],
            "files": result["files"],
            "created_by_id": actor_id,
            "expires_at": _iso(_now() + timedelta(days=access_days())),
        },
    )
    record.username = person.username
    return record


def push_release(short_code: str, release_id: str, release_path: Optional[str]) -> dict:
    """Copy an approved release from the API's disk to staging at <code>/<release>/."""
    if not release_path:
        raise cai.ProvisioningError(f"Release {release_id} has no folder on the API's disk")
    from app.blobstore import any_path

    return cai.upload_folder(any_path(release_path), release_folder(short_code, release_id))


def push_after_approval(short_code: str, release_id: str, release_path: Optional[str]) -> None:
    """Background step after a release is approved. Never fails the approval:
    if staging isn't set up here (e.g. local runs) or the copy fails, it is
    logged and the project page offers to copy again."""
    if not (os.environ.get("STAGING_PROJECT_ID") or "").strip():
        return
    try:
        result = push_release(short_code, release_id, release_path)
        log.info("cai_release_pushed", release_id=release_id, **result)
    except Exception as exc:
        log.error("cai_release_push_failed", release_id=release_id, error=str(exc)[:300])


def sync_staging(cursor, project_id: str) -> dict:
    """Copy the project's latest approved release to staging (missing files only)."""
    project = projects_crud.get_project_or_404(cursor, project_id)
    release = _latest_approved(cursor, project.id)
    if release is None:
        raise ValidationError("The project has no approved Zone 2 release yet")
    try:
        push_release(project.short_code, release.id, release.release_path)
    except cai.ProvisioningError as exc:
        raise ValidationError(str(exc)) from exc
    return release_status(cursor, project.id)


def release_status(cursor, project_id: str) -> dict:
    """The release a new researcher project would get, and whether staging has it yet."""
    project = projects_crud.get_project_or_404(cursor, project_id)
    release = _latest_approved(cursor, project.id)
    out = {"release_id": None, "folder": None, "in_staging": False, "error": None}
    if release is None:
        return out
    folder = release_folder(project.short_code, release.id)
    out.update(release_id=release.id, folder=folder)
    try:
        out["in_staging"] = cai.in_staging(folder)
    except cai.ProvisioningError as exc:
        out["error"] = str(exc)
    return out


def _active(cursor, record_id: str) -> CaiProject:
    record = crud.get_or_404(cursor, record_id)
    if record.status != crud.ACTIVE:
        raise ValidationError("This researcher project has already been removed")
    return record


def extend(cursor, record_id: str) -> CaiProject:
    record = _active(cursor, record_id)
    start = max(_parse(record.expires_at) or _now(), _now())
    return crud.update(cursor, record.id, {"expires_at": _iso(start + timedelta(days=access_days()))})


def end(cursor, record_id: str, actor_id: str, reason: str) -> CaiProject:
    record = _active(cursor, record_id)
    try:
        cai.deprovision(record.cai_project_id)
    except cai.ProvisioningError as exc:
        raise ValidationError(f"Could not delete the Cloudera AI project: {exc}") from exc
    ended = crud.update(
        cursor,
        record.id,
        {"status": crud.ENDED, "ended_at": _iso(_now()), "ended_by_id": actor_id,
         "ended_reason": reason},
    )
    _clear_staging_if_unused(cursor, ended)
    return ended


def _clear_staging_if_unused(cursor, record: CaiProject) -> None:
    """Delete the release folder from staging once no active researcher project uses it.

    Every fork copies all of staging, so it should hold only what is in use.
    The release stays on the API's disk and is copied back when needed, so a
    failure here is logged, never raised: the researcher project is already gone.
    """
    still_used = any(
        other.release_id == record.release_id
        for other in crud.list_cai_projects(cursor, record.project_id, crud.ACTIVE)
    )
    if still_used:
        return
    try:
        project = projects_crud.get_project_or_404(cursor, record.project_id)
        removed = cai.remove_from_staging(release_folder(project.short_code, record.release_id))
        log.info("cai_staging_cleared", release_id=record.release_id, removed=removed)
    except Exception as exc:
        log.error("cai_staging_clear_failed", release_id=record.release_id, error=str(exc)[:300])


def end_all_for_project(cursor, project_id: str, actor_id: str, reason: str) -> int:
    """Called before a Hive project ends; refuses to go on if any deletion fails."""
    active = crud.list_cai_projects(cursor, project_id, crud.ACTIVE)
    for record in active:
        end(cursor, record.id, actor_id, reason)
    _clear_project_from_staging(cursor, project_id)
    return len(active)


def _clear_project_from_staging(cursor, project_id: str) -> None:
    """Delete the project's whole <code>/ folder from staging when the project ends.

    Releases are copied to staging on approval, so a project that ends without
    any researcher project would otherwise leave its folder there for good.
    Best-effort, like _clear_staging_if_unused."""
    if not (os.environ.get("STAGING_PROJECT_ID") or "").strip():
        return
    try:
        project = projects_crud.get_project_or_404(cursor, project_id)
        removed = cai.remove_from_staging(project.short_code)
        log.info("cai_staging_project_cleared", project_id=project_id, removed=removed)
    except Exception as exc:
        log.error("cai_staging_clear_failed", project_id=project_id, error=str(exc)[:300])


def expire_due(cursor, now: Optional[datetime] = None) -> List[CaiProject]:
    moment = now or _now()
    expired = []
    for record in crud.list_cai_projects(cursor, status=crud.ACTIVE):
        due = _parse(record.expires_at)
        if not due or due > moment:
            continue
        try:
            expired.append(end(cursor, record.id, "cai-cleanup", "access expired"))
        except Exception as exc:
            log.error("cai_expiry_failed", record_id=record.id, error=str(exc))
    return expired
