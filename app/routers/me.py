from fastapi import APIRouter, Depends

from app.schemas import User
from app.security import get_current_user

router = APIRouter(prefix="/me", tags=["me"])


@router.get("", response_model=User)
def read_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.get("/permissions", response_model=list[str])
def read_my_permissions(current_user: User = Depends(get_current_user)):
    return current_user.permissions
