"""Permission enforcement (RBAC).

Caller identity comes from the `X-User-Id` header. That is a deliberate
local stand-in: no auth scheme was specified, and on Cloudera AI the
authenticated principal would arrive from the platform (Kerberos/Knox)
instead. Swapping the source means changing only `_current_user_id` --
route code and permission strings stay identical, so nothing branches on
environment.

Permission strings are "<model>:<action>", e.g. 'users:read'.
"""
from typing import Optional

import structlog
from fastapi import Depends, Header

from app.crud.users import get_user
from app.db import get_cursor
from app.errors import AuthError, PermissionDeniedError
from app.logging_setup import get_logger
from app.schemas import User

log = get_logger(__name__)

# Every grant the API recognises. Roles are validated against this so a
# typo'd permission ('user:read') fails loudly at role-write time instead
# of silently never matching at request time.
KNOWN_PERMISSIONS = frozenset(
    f"{model}:{action}"
    for model in ("users", "patients", "roles", "logs")
    for action in ("read", "create", "update", "delete")
)


def _current_user_id(x_user_id: Optional[str] = Header(default=None)) -> str:
    if not x_user_id:
        raise AuthError("Missing X-User-Id header")
    return x_user_id


def get_current_user(
    user_id: str = Depends(_current_user_id),
    cursor=Depends(get_cursor),
) -> User:
    """Resolves the acting user, with role_name + permissions already
    joined in by crud.users. Shares the request's cursor via FastAPI
    dependency caching, so this costs no extra Hive connection."""
    user = get_user(cursor, user_id)
    if user is None:
        raise AuthError(f"Unknown user '{user_id}'")
    if not user.is_active:
        raise AuthError(f"User '{user_id}' is inactive")

    structlog.contextvars.bind_contextvars(actor_id=user.id, actor_role=user.role_name)
    return user


def require_permission(permission: str):
    """Dependency factory: require_permission('users:read').

    Returns the acting user so handlers that need the caller can take it
    straight from this dependency.
    """

    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if permission not in current_user.permissions:
            log.warning(
                "permission_denied",
                required=permission,
                granted=current_user.permissions,
            )
            raise PermissionDeniedError(
                f"Permission '{permission}' is required for this operation"
            )
        return current_user

    return dependency
