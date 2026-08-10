"""Audit log endpoints: create, get_all, get by id."""
from typing import List, Optional

from fastapi import APIRouter, Depends, Query

from app.crud import audit_log as crud
from app.db import get_cursor
from app.schemas import AuditLog, AuditLogCreate, User
from app.security import require_permission

router = APIRouter(prefix="/logs", tags=["audit-log"])


@router.post("", response_model=AuditLog, status_code=201)
def create_audit_log(
    payload: AuditLogCreate,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("log:create")),
):
    return crud.create_audit_log(cursor, payload)


@router.get("", response_model=List[AuditLog])
def list_audit_logs(
    entity_type: Optional[str] = Query(default=None),
    entity_id: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("log:view")),
):
    return crud.list_audit_logs(
        cursor, entity_type=entity_type, entity_id=entity_id, limit=limit
    )


@router.get("/{audit_id}", response_model=AuditLog)
def get_audit_log(
    audit_id: str,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("log:view")),
):
    return crud.get_audit_log(cursor, audit_id)
