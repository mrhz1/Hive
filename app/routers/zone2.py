from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Request

from app import zone2
from app.audit import record_audit
from app.crud import projects as projects_crud
from app.db import get_cursor
from app.project_schemas import ProjectRelease, ReleaseDecision, ReleaseSummary
from app.schemas import User
from app.security import require_permission

router = APIRouter(prefix="/zone2", tags=["zone2"])


def _with_project(cursor, release: ProjectRelease, detail: bool = False) -> ReleaseSummary:
    project = projects_crud.get_project(cursor, release.project_id)
    extra = zone2.summary(release) if detail else {}
    return ReleaseSummary(
        **release.model_dump(),
        project_name=project.name if project else "",
        project_short_code=project.short_code if project else "",
        **extra,
    )


def _audit(background, request, action, release, actor, new):
    background.add_task(
        record_audit,
        action=action,
        entity_type="project_release",
        entity_id=release.id,
        user_id=actor.id,
        old_values={"status": "in_review", "project_id": release.project_id},
        new_values=new,
        request_id=request.headers.get("X-Request-ID"),
    )


@router.get("/releases", response_model=List[ReleaseSummary])
def list_releases(
    status: Optional[str] = "in_review",
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("zone2:review")),
):
    """The Zone 2 inbox: releases waiting for review (or any status)."""
    releases = projects_crud.list_releases(cursor, status=status or None)
    return [_with_project(cursor, r) for r in releases]


@router.get("/releases/{release_id}", response_model=ReleaseSummary)
def get_release(
    release_id: str,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("zone2:review")),
):
    release = projects_crud.get_release_or_404(cursor, release_id)
    return _with_project(cursor, release, detail=True)


@router.post("/releases/{release_id}/approve", response_model=ReleaseSummary)
def approve_release(
    release_id: str,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("zone2:review")),
):
    release = zone2.approve(cursor, release_id, actor.id)
    _audit(background, request, "UPDATE", release, actor,
           {"status": "approved", "release_path": release.release_path})
    return _with_project(cursor, release)


@router.post("/releases/{release_id}/reject", response_model=ReleaseSummary)
def reject_release(
    release_id: str,
    payload: ReleaseDecision,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("zone2:review")),
):
    release = zone2.reject(cursor, release_id, actor.id, payload.reason)
    _audit(background, request, "UPDATE", release, actor,
           {"status": "rejected", "reason": release.status_reason})
    return _with_project(cursor, release)
