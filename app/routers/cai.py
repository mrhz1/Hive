from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Request

from app import cai_projects
from app import cai_provisioning as cai
from app.audit import record_audit
from app.db import authoritative, get_cursor
from app.errors import ValidationError
from app.project_schemas import CaiEnd, CaiProject, CaiProvision, CaiReleaseStatus, CaiStagingFile
from app.schemas import User
from app.security import require_permission

# Every route here acts with the service account's rights in Cloudera AI, so
# all of them need cai:provision, which only admins get. Researchers never do.
PROVISION = "cai:provision"

router = APIRouter(prefix="/cai", tags=["cai"])


def _audit(background, request, action, record: CaiProject, actor, old=None, new=None):
    background.add_task(
        record_audit,
        action=action,
        entity_type="cai_project",
        entity_id=record.id,
        user_id=actor.id,
        old_values=old,
        new_values=new,
        request_id=request.headers.get("X-Request-ID"),
    )


@router.get("/staging/files", response_model=List[CaiStagingFile])
def staging_files(_actor: User = Depends(require_permission(PROVISION))):
    try:
        return cai.list_staging_files()
    except cai.ProvisioningError as exc:
        raise ValidationError(str(exc)) from exc


@router.get("/projects", response_model=List[CaiProject])
def list_projects(
    project_id: Optional[str] = None,
    status: Optional[str] = None,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission(PROVISION)),
):
    with authoritative(cursor):
        return cai_projects.list_for(cursor, project_id, status)


@router.get("/release-status/{project_id}", response_model=CaiReleaseStatus)
def release_status(
    project_id: str,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission(PROVISION)),
):
    with authoritative(cursor):
        return cai_projects.release_status(cursor, project_id)


@router.post("/release-status/{project_id}/sync", response_model=CaiReleaseStatus)
def sync_release(
    project_id: str,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission(PROVISION)),
):
    """Copy the latest approved release to the staging project (missing files only)."""
    with authoritative(cursor):
        return cai_projects.sync_staging(cursor, project_id)


@router.post("/projects", response_model=CaiProject, status_code=201)
def provision(
    payload: CaiProvision,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission(PROVISION)),
):
    record = cai_projects.provision(cursor, payload, actor.id)
    _audit(
        background, request, "CREATE", record, actor,
        new={"project_id": record.project_id, "user": record.cai_username,
             "release_id": record.release_id, "cai_project_id": record.cai_project_id,
             "files": len(record.files), "expires_at": record.expires_at},
    )
    return record


@router.post("/projects/{record_id}/extend", response_model=CaiProject)
def extend(
    record_id: str,
    payload: CaiEnd,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission(PROVISION)),
):
    record = cai_projects.extend(cursor, record_id)
    _audit(background, request, "UPDATE", record, actor,
           new={"expires_at": record.expires_at, "reason": payload.reason})
    return record


@router.post("/projects/{record_id}/end", response_model=CaiProject)
def end(
    record_id: str,
    payload: CaiEnd,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission(PROVISION)),
):
    record = cai_projects.end(cursor, record_id, actor.id, payload.reason.strip())
    _audit(background, request, "DELETE", record, actor,
           old={"cai_project_id": record.cai_project_id}, new={"reason": record.ended_reason})
    return record
