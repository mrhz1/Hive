from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from fastapi.responses import FileResponse

from app import intake_notices, zone2
from app.access_log import READ, record_access
from app.audit import record_audit
from app.crud import patient_applications as applications_crud
from app.crud import projects as projects_crud
from app.db import get_cursor
from app.preview import render_dicom_png
from app.project_schemas import (
    ProjectRelease,
    ReleaseDecision,
    ReleaseDocument,
    ReleaseSummary,
)
from app.schemas import User
from app.security import require_permission
from app.storage import guess_mime_type

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


@router.get("/releases/{release_id}/documents", response_model=List[ReleaseDocument])
def release_documents(
    release_id: str,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("zone2:review")),
):
    """The files in a release, to spot-check before approving."""
    release = projects_crud.get_release_or_404(cursor, release_id)
    return [ReleaseDocument(**row) for row in zone2.release_documents(release)]


def _opened(actor: User, release_id: str, document_id: str) -> None:
    record_access(
        READ,
        actor=actor,
        resource_type="release_document",
        resource_id=f"{release_id}/{document_id}",
        identified=False,
    )


@router.get("/releases/{release_id}/documents/{document_id}/content")
def release_document_content(
    release_id: str,
    document_id: str,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("zone2:review")),
):
    release = projects_crud.get_release_or_404(cursor, release_id)
    path = zone2.release_file(release, document_id)
    _opened(actor, release_id, document_id)
    return FileResponse(
        path,
        media_type=guess_mime_type(path.name, None),
        filename=path.name,
        content_disposition_type="inline",
    )


@router.get("/releases/{release_id}/documents/{document_id}/image")
def release_document_image(
    release_id: str,
    document_id: str,
    frame: int = 0,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("zone2:review")),
):
    """A DICOM frame as PNG; the frame count is in X-Frame-Count."""
    release = projects_crud.get_release_or_404(cursor, release_id)
    path = zone2.release_file(release, document_id)
    content, frames = render_dicom_png(path, frame)
    _opened(actor, release_id, document_id)
    return Response(
        content=content,
        media_type="image/png",
        headers={
            "X-Frame-Count": str(frames),
            "Access-Control-Expose-Headers": "X-Frame-Count",
        },
    )


@router.post(
    "/releases/{release_id}/documents/{document_id}/flag",
    response_model=ReleaseSummary,
)
def flag_release_document(
    release_id: str,
    document_id: str,
    payload: ReleaseDecision,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("zone2:review")),
):
    """This document still identifies someone: reject the release and send
    the document to Rejections."""
    release, record = zone2.flag_document(
        cursor, release_id, document_id, actor.id, payload.reason
    )
    _audit(background, request, "UPDATE", release, actor,
           {"status": "rejected", "reason": release.status_reason,
            "flagged_document": document_id, "file_id": record.id})
    background.add_task(
        intake_notices.notify_file_rejected,
        application_id=record.application_id,
        patient_id=getattr(
            applications_crud.get_application(cursor, record.application_id),
            "patient_id",
            "",
        ),
        file_name=record.deidentified_file_name or record.original_file_name,
        actor=actor,
        note=f"flagged in Zone 2 release {release.id}: {(payload.reason or '').strip()}",
    )
    return _with_project(cursor, release)
