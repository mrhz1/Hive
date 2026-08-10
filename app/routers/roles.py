from typing import List

from fastapi import APIRouter, Depends

from app.crud import roles as crud
from app.db import get_cursor
from app.errors import NotFoundError, ValidationError
from app.schemas import Role, RoleCreate, RoleUpdate, User
from app.security import KNOWN_PERMISSIONS, require_permission

router = APIRouter(prefix="/roles", tags=["roles"])


def _validate_permissions(permissions: List[str]) -> None:
    """Reject unknown grants at write time."""
    unknown = sorted(set(permissions) - KNOWN_PERMISSIONS)
    if unknown:
        raise ValidationError(
            f"Unknown permissions: {', '.join(unknown)}. "
            f"Valid values: {', '.join(sorted(KNOWN_PERMISSIONS))}"
        )


@router.post("", response_model=Role, status_code=201)
def create_role(
    payload: RoleCreate,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("role:create")),
):
    _validate_permissions(payload.permissions)
    return crud.create_role(cursor, payload)


@router.get("", response_model=List[Role])
def list_roles(
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("role:view")),
):
    return crud.list_roles(cursor)


@router.get("/{role_id}", response_model=Role)
def get_role(
    role_id: str,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("role:view")),
):
    role = crud.get_role(cursor, role_id)
    if role is None:
        raise NotFoundError(f"Role '{role_id}' not found")
    return role


@router.put("/{role_id}", response_model=Role)
def update_role(
    role_id: str,
    payload: RoleUpdate,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("role:update")),
):
    if payload.permissions is not None:
        _validate_permissions(payload.permissions)
    return crud.update_role(cursor, role_id, payload)


@router.delete("/{role_id}", status_code=204)
def delete_role(
    role_id: str,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("role:delete")),
):
    crud.delete_role(cursor, role_id)
