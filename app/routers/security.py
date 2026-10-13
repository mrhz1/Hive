"""Section 4: locking the app and recording security incidents."""

from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from pydantic import BaseModel

from app import incidents, lockdown
from app.audit import record_audit
from app.db import get_cursor
from app.schemas import User
from app.security import get_current_user, require_permission

router = APIRouter(tags=["security"])


class LockRequest(BaseModel):
    reason: Optional[str] = None
    level: str = "critical"


class Reason(BaseModel):
    reason: Optional[str] = None


class SentRequest(BaseModel):
    report: str


def _audit(background, request, action, entity_type, entity_id, actor, old=None, new=None):
    background.add_task(
        record_audit,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        user_id=actor.id,
        old_values=old,
        new_values=new,
        request_id=request.headers.get("X-Request-ID"),
    )


# --- lockdown ----------------------------------------------------------------------


@router.get("/security/lockdown", response_model=lockdown.LockdownState)
def lockdown_state(_actor: User = Depends(get_current_user)):
    """Whether the app is locked; anyone signed in may ask, even when locked."""
    return lockdown.state()


@router.post("/security/lockdown", response_model=lockdown.LockdownState)
def lock_app(
    payload: LockRequest,
    background: BackgroundTasks,
    request: Request,
    actor: User = Depends(require_permission(lockdown.MANAGE)),
):
    after = lockdown.lock(payload.reason or "", payload.level, actor.username)
    _audit(background, request, "UPDATE", "lockdown", "app", actor,
           old={"locked": False}, new=after.model_dump())
    return after


@router.post("/security/unlock", response_model=lockdown.LockdownState)
def unlock_app(
    payload: Reason,
    background: BackgroundTasks,
    request: Request,
    actor: User = Depends(require_permission(lockdown.MANAGE)),
):
    before = lockdown.state(fresh=True)
    after = lockdown.unlock(payload.reason or "", actor.username)
    _audit(background, request, "UPDATE", "lockdown", "app", actor,
           old=before.model_dump(), new={"locked": False, "reason": payload.reason})
    return after


# --- incidents ---------------------------------------------------------------------


@router.get("/incidents", response_model=List[incidents.Incident])
def list_incidents(
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("security:view")),
):
    return incidents.list_incidents(cursor)


@router.post("/incidents", response_model=incidents.Incident, status_code=201)
def create_incident(
    payload: incidents.IncidentCreate,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission(lockdown.MANAGE)),
):
    incident = incidents.create(cursor, payload, actor.id)
    _audit(background, request, "CREATE", "incident", incident.id, actor,
           new=incident.model_dump(mode="json"))
    return incident


@router.get("/incidents/{incident_id}", response_model=incidents.Incident)
def get_incident(
    incident_id: str,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("security:view")),
):
    return incidents.get_or_404(cursor, incident_id)


@router.put("/incidents/{incident_id}", response_model=incidents.Incident)
def update_incident(
    incident_id: str,
    payload: incidents.IncidentFields,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission(lockdown.MANAGE)),
):
    before = incidents.get_or_404(cursor, incident_id)
    after = incidents.update(cursor, incident_id, payload)
    _audit(background, request, "UPDATE", "incident", incident_id, actor,
           old=before.model_dump(mode="json"), new=after.model_dump(mode="json"))
    return after


@router.post("/incidents/{incident_id}/sent", response_model=incidents.Incident)
def mark_report_sent(
    incident_id: str,
    payload: SentRequest,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission(lockdown.MANAGE)),
):
    after = incidents.mark_sent(cursor, incident_id, payload.report)
    _audit(background, request, "UPDATE", "incident", incident_id, actor,
           new={f"{payload.report}_sent_at": getattr(after, f"{payload.report}_sent_at")})
    return after


@router.post("/incidents/{incident_id}/close", response_model=incidents.Incident)
def close_incident(
    incident_id: str,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission(lockdown.MANAGE)),
):
    after = incidents.close(cursor, incident_id)
    _audit(background, request, "UPDATE", "incident", incident_id, actor,
           new={"status": after.status, "closed_at": after.closed_at})
    return after


@router.get("/incidents/{incident_id}/report")
def incident_report(
    incident_id: str,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("security:view")),
):
    """The breach report as a Word document."""
    incident = incidents.get_or_404(cursor, incident_id)
    return Response(
        content=incidents.report_docx(incident),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="incident-{incident_id[:8]}.docx"'},
    )
