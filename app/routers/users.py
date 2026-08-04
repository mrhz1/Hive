from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, Request

from app.audit import record_audit
from app.crud import users as crud
from app.db import get_cursor
from app.schemas import User, UserCreate, UserUpdate
from app.security import require_permission

router = APIRouter(prefix="/users", tags=["users"])


def _snapshot(user: User) -> dict:
    """What goes into the audit log. Excludes the joined role_name /
    permissions -- those belong to the role, not to this row's state."""
    return user.model_dump(exclude={"role_name", "permissions"}, mode="json")


@router.post("", response_model=User, status_code=201)
def create_user(
    payload: UserCreate,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("users:create")),
):
    user = crud.create_user(cursor, payload)
    background.add_task(
        record_audit,
        action="CREATE",
        entity_type="user",
        entity_id=user.id,
        old_values=None,  # nothing existed before a create
        new_values=_snapshot(user),
        request_id=request.headers.get("X-Request-ID"),
    )
    return user


@router.get("", response_model=List[User])
def list_users(
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("users:read")),
):
    return crud.list_users(cursor)


@router.get("/{user_id}", response_model=User)
def get_user(
    user_id: str,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("users:read")),
):
    return crud.get_user_or_404(cursor, user_id)


@router.put("/{user_id}", response_model=User)
def update_user(
    user_id: str,
    payload: UserUpdate,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("users:update")),
):
    before = crud.get_user_or_404(cursor, user_id)
    after = crud.update_user(cursor, user_id, payload)
    background.add_task(
        record_audit,
        action="UPDATE",
        entity_type="user",
        entity_id=user_id,
        old_values=_snapshot(before),
        new_values=_snapshot(after),
        request_id=request.headers.get("X-Request-ID"),
    )
    return after


@router.delete("/{user_id}", status_code=204)
def delete_user(
    user_id: str,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("users:delete")),
):
    deleted = crud.delete_user(cursor, user_id)
    background.add_task(
        record_audit,
        action="DELETE",
        entity_type="user",
        entity_id=user_id,
        old_values=_snapshot(deleted),
        new_values=None,  # nothing remains after a delete
        request_id=request.headers.get("X-Request-ID"),
    )
