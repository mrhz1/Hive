"""Current-user endpoints.

The dashboard has no login screen: it asks the API who the caller is and
renders from the permissions that come back. On Cloudera AI the caller
will be the platform-authenticated principal; locally it is the
X-User-Id header. Either way the frontend reads identity from here rather
than deciding anything itself.
"""
from fastapi import APIRouter, Depends

from app.crud import users as crud
from app.db import get_cursor
from app.errors import ValidationError
from app.schemas import ProfileUpdate, User, UserUpdate
from app.security import get_current_user

router = APIRouter(prefix="/me", tags=["me"])


@router.get("", response_model=User)
def read_me(current_user: User = Depends(get_current_user)):
    """No permission required -- every authenticated caller may read
    their own record, otherwise the dashboard could not even boot."""
    return current_user


@router.put("", response_model=User)
def update_me(
    payload: ProfileUpdate,
    cursor=Depends(get_cursor),
    current_user: User = Depends(get_current_user),
):
    """Self-service profile update.

    Deliberately NOT gated on 'user:update': a user editing their own
    name should not need permission to edit everyone. The trade-off is
    that this becomes a privilege-escalation path if it accepts every
    field, so ProfileUpdate exposes only first_name/last_name/email --
    never role_id, status or is_active. Changing those still requires
    'user:update' via PUT /users/{id}.
    """
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        return current_user

    return crud.update_user(cursor, current_user.id, UserUpdate(**fields))


@router.get("/permissions", response_model=list[str])
def read_my_permissions(current_user: User = Depends(get_current_user)):
    return current_user.permissions
