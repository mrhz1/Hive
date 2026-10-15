from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import BaseModel

from app import abstraction
from app.access_log import EXPORT, record_access
from app.audit import record_audit
from app.crud import abstraction_folders as crud
from app.crud import users as users_crud
from app.db import get_cursor
from app.errors import PermissionDeniedError, ValidationError
from app.logging_setup import get_logger
from app.schemas import (
    AbstractionCriteria,
    AbstractionDelete,
    AbstractionDocument,
    AbstractionFolder,
    AbstractionFolderCreate,
    AbstractionPreview,
    User,
)
from app.security import require_permission

log = get_logger(__name__)

router = APIRouter(prefix="/abstraction-folders", tags=["abstraction"])

PREVIEW_ROWS = 200
MANAGE_ALL = "abstraction:manage"


class Regenerated(BaseModel):
    folder: AbstractionFolder
    missing: int


def _audit(background, request, action, folder_id, actor, old=None, new=None):
    background.add_task(
        record_audit,
        action=action,
        entity_type="abstraction_folder",
        entity_id=folder_id,
        user_id=actor.id,
        old_values=old,
        new_values=new,
        request_id=request.headers.get("X-Request-ID"),
    )


def _with_owner_names(cursor, folders: List[AbstractionFolder]) -> List[AbstractionFolder]:
    names = {user.id: user.username for user in users_crud.list_users(cursor)}
    for folder in folders:
        folder.owner_username = names.get(folder.owner_id or "")
        folder.assigned_to_username = names.get(folder.assigned_to_id or "")
    return folders


def _visible_to(folder: AbstractionFolder, actor: User) -> bool:
    return (
        MANAGE_ALL in actor.permissions
        or folder.owner_id == actor.id
        or folder.assigned_to_id == actor.id
    )


def _own_or_managed(cursor, folder_id: str, actor: User) -> AbstractionFolder:
    folder = crud.get_folder_or_404(cursor, folder_id)
    if not _visible_to(folder, actor):
        raise PermissionDeniedError("This folder belongs to someone else")
    return folder


def _assignee(cursor, payload: AbstractionFolderCreate, actor: User):
    if not payload.assigned_to_id or payload.assigned_to_id == actor.id:
        return None
    person = users_crud.get_user_or_404(cursor, payload.assigned_to_id)
    if not person.is_active:
        raise ValidationError(f"'{person.username}' is not active")
    return person


def _snapshot(folder: AbstractionFolder) -> dict:
    return folder.model_dump(mode="json", exclude={"owner_username", "assigned_to_username"})


@router.get("", response_model=List[AbstractionFolder])
def list_folders(
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("abstraction:view")),
):
    folders = [f for f in crud.list_folders(cursor) if _visible_to(f, actor)]
    return _with_owner_names(cursor, folders)


@router.post("/preview", response_model=AbstractionPreview)
def preview(
    criteria: AbstractionCriteria,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("abstraction:create")),
):
    docs = abstraction.matching(cursor, criteria)
    return AbstractionPreview(
        total=len(docs),
        patients=len({d.patient_id for d in docs}),
        documents=docs[:PREVIEW_ROWS],
    )


@router.post("", response_model=AbstractionFolder, status_code=201)
def create_folder(
    payload: AbstractionFolderCreate,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("abstraction:create")),
):
    folder = abstraction.create(cursor, payload, actor, _assignee(cursor, payload, actor))
    record_access(
        EXPORT,
        actor=actor,
        resource_type="abstraction_folder",
        resource_id=folder.id,
        identified=False,
        record_count=folder.file_count,
        detail=f"copied to abstraction folder '{folder.name}'",
    )
    _audit(background, request, "CREATE", folder.id, actor, new=_snapshot(folder))
    return _with_owner_names(cursor, [folder])[0]


@router.get("/{folder_id}", response_model=AbstractionFolder)
def get_folder(
    folder_id: str,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("abstraction:view")),
):
    return _with_owner_names(cursor, [_own_or_managed(cursor, folder_id, actor)])[0]


@router.get("/{folder_id}/documents", response_model=List[AbstractionDocument])
def folder_documents(
    folder_id: str,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("abstraction:view")),
):
    return abstraction.documents(cursor, _own_or_managed(cursor, folder_id, actor))


@router.post("/{folder_id}/extend", response_model=AbstractionFolder)
def extend_folder(
    folder_id: str,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("abstraction:update")),
):
    before = _own_or_managed(cursor, folder_id, actor)
    after = abstraction.extend(cursor, before)
    _audit(
        background, request, "UPDATE", folder_id, actor,
        old={"expires_at": before.expires_at}, new={"expires_at": after.expires_at},
    )
    return _with_owner_names(cursor, [after])[0]


@router.post("/{folder_id}/regenerate", response_model=Regenerated)
def regenerate_folder(
    folder_id: str,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("abstraction:update")),
):
    before = _own_or_managed(cursor, folder_id, actor)
    after, missing = abstraction.regenerate(cursor, before)
    record_access(
        EXPORT,
        actor=actor,
        resource_type="abstraction_folder",
        resource_id=folder_id,
        identified=False,
        record_count=after.file_count,
        detail=f"abstraction folder '{after.name}' made again",
    )
    _audit(
        background, request, "UPDATE", folder_id, actor,
        old=_snapshot(before), new=dict(_snapshot(after), missing=missing),
    )
    return Regenerated(folder=_with_owner_names(cursor, [after])[0], missing=missing)


@router.post("/{folder_id}/delete", response_model=AbstractionFolder)
def delete_folder(
    folder_id: str,
    payload: AbstractionDelete,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("abstraction:update")),
):
    before = _own_or_managed(cursor, folder_id, actor)
    after = abstraction.delete(cursor, before, actor.id, payload.reason)
    _audit(background, request, "DELETE", folder_id, actor, old=_snapshot(before), new=_snapshot(after))
    return _with_owner_names(cursor, [after])[0]
