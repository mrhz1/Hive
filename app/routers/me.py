"""Current-user endpoints."""
from fastapi import APIRouter, Depends

from app.crud import users as crud
from app.db import get_cursor
from app.errors import ValidationError
from app.schemas import ProfileUpdate, User, UserUpdate
from app.security import get_current_user

router = APIRouter(prefix="/me", tags=["me"])


@router.get("", response_model=User)
def read_me(current_user: User = Depends(get_current_user)):
    """No permission required -- every authenticated caller may read their own record, otherwise the dashboard could not even boot."""
    return current_user


@router.put("", response_model=User)
def update_me(
    payload: ProfileUpdate,
    cursor=Depends(get_cursor),
    current_user: User = Depends(get_current_user),
):
    """Self-service profile update."""
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        return current_user

    return crud.update_user(cursor, current_user.id, UserUpdate(**fields))


@router.get("/permissions", response_model=list[str])
def read_my_permissions(current_user: User = Depends(get_current_user)):
    return current_user.permissions
