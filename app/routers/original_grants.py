from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, Request

from app import original_access
from app.audit import record_audit
from app.crud import original_grants as crud
from app.crud import patient_application_files as files_crud
from app.crud import users as users_crud
from app.db import get_cursor
from app.errors import ValidationError
from app.schemas import OriginalGrant, OriginalGrantCreate, User
from app.security import get_current_user, require_permission

router = APIRouter(tags=["original-grants"])


def _audit(background, request, action, grant: OriginalGrant, actor: User):
    background.add_task(
        record_audit,
        action=action,
        entity_type="original_grant",
        entity_id=grant.id,
        user_id=actor.id,
        old_values=None,
        new_values=grant.model_dump(mode="json", exclude={"username", "granted_by_username"}),
        request_id=request.headers.get("X-Request-ID"),
    )


def _with_names(cursor, grants: List[OriginalGrant]) -> List[OriginalGrant]:
    names = {u.id: u.username for u in users_crud.list_users(cursor)}
    for grant in grants:
        grant.username = names.get(grant.user_id)
        grant.granted_by_username = names.get(grant.granted_by_id or "")
    return grants


@router.get("/files/{file_id}/original-grants", response_model=List[OriginalGrant])
def list_grants(
    file_id: str,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission(original_access.GRANT)),
):
    files_crud.get_file_or_404(cursor, file_id)
    return _with_names(cursor, crud.list_for_file(cursor, file_id))


@router.post("/files/{file_id}/original-grants", response_model=OriginalGrant, status_code=201)
def grant(
    file_id: str,
    payload: OriginalGrantCreate,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission(original_access.GRANT)),
):
    files_crud.get_file_or_404(cursor, file_id)
    person = users_crud.get_user_or_404(cursor, payload.user_id)
    if not person.is_active:
        raise ValidationError(f"'{person.username}' is not active")
    if crud.has_active(cursor, file_id, person.id):
        raise ValidationError(f"'{person.username}' can already open this original")
    created = crud.create(cursor, file_id, person.id, payload.reason, actor.id)
    _audit(background, request, "CREATE", created, actor)
    return _with_names(cursor, [created])[0]


@router.post(
    "/files/{file_id}/original-grants/{grant_id}/revoke", response_model=OriginalGrant
)
def revoke(
    file_id: str,
    grant_id: str,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission(original_access.GRANT)),
):
    existing = crud.get_or_404(cursor, grant_id)
    if existing.file_id != file_id:
        raise ValidationError("This grant belongs to another file")
    if existing.revoked_at:
        raise ValidationError("This grant was already taken back")
    revoked = crud.revoke(cursor, grant_id, actor.id)
    _audit(background, request, "UPDATE", revoked, actor)
    return _with_names(cursor, [revoked])[0]


@router.get("/me/original-grants", response_model=List[str])
def my_grants(
    cursor=Depends(get_cursor),
    actor: User = Depends(get_current_user),
):
    return sorted({g.file_id for g in crud.active_for_user(cursor, actor.id)})
