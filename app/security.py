"""Permission enforcement (RBAC).

Caller identity is the username in the `REMOTE-USER` header -- the
principal the platform already authenticated (Kerberos/Knox on Cloudera
AI) and passed down. The app authenticates nobody itself; it only
resolves that name to a user row and reads their grants. Swapping the
source means changing only `_current_username` -- route code and
permission strings stay identical, so nothing branches on environment.

Permission strings are "<model>:<action>", e.g. 'user:view'.
"""
import structlog
from fastapi import Depends, Request

from app.crud.users import _find_by_username
from app.db import get_cursor
from app.errors import AuthError, PermissionDeniedError
from app.logging_setup import get_logger
from app.schemas import User

log = get_logger(__name__)

# Every grant the API recognises. Roles are validated against this so a
# typo'd permission ('user:red') fails loudly at role-write time instead
# of silently never matching at request time.
PERMISSION_MODELS = ("user", "patient", "role", "log", "application")
PERMISSION_ACTIONS = ("view", "create", "update", "delete")

KNOWN_PERMISSIONS = frozenset(
    f"{model}:{action}"
    for model in PERMISSION_MODELS
    for action in PERMISSION_ACTIONS
)


def _current_username(request: Request) -> str:
    """The authenticated principal, as the platform handed it over.

    Read off the raw request rather than declared as a Header parameter:
    header names are matched case-insensitively either way, but this
    keeps the exact spelling the platform sets visible at the one place
    identity enters the app.
    """
    username = request.headers.get("REMOTE-USER")
    if not username:
        raise AuthError("Missing REMOTE-USER header")
    return username


def get_current_user(
    username: str = Depends(_current_username),
    cursor=Depends(get_cursor),
) -> User:
    """Resolves the acting user, with role_name + permissions already
    joined in by crud.users. Shares the request's cursor via FastAPI
    dependency caching, so this costs no extra Hive connection."""
    user = _find_by_username(cursor, username)
    if user is None:
        raise AuthError(f"Unknown user '{username}'")
    if not user.is_active:
        raise AuthError(f"User '{username}' is inactive")

    structlog.contextvars.bind_contextvars(actor_id=user.id, actor_role=user.role_name)
    return user


def require_permission(permission: str):
    """Dependency factory: require_permission('user:view').

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
