"""Permission enforcement (RBAC)."""
import structlog
from fastapi import Depends, Request

from app.access_log import AUTH_FAILURE, DENIED, FAILURE, record_access
from app.crud.users import _find_by_username
from app.db import get_cursor
from app.errors import AuthError, PermissionDeniedError
from app.logging_setup import get_logger
from app.schemas import User

log = get_logger(__name__)

PERMISSION_MODELS = ("user", "patient", "role", "log", "application", "files")
PERMISSION_ACTIONS = ("view", "create", "update", "delete")

MODEL_ACTIONS = {
    model: PERMISSION_ACTIONS for model in PERMISSION_MODELS if model != "files"
}
MODEL_ACTIONS["files"] = ("read", "upload", "download", "delete")

KNOWN_PERMISSIONS = frozenset(
    f"{model}:{action}"
    for model, actions in MODEL_ACTIONS.items()
    for action in actions
)


def _current_username(request: Request) -> str:
    """The authenticated principal, as the platform handed it over."""
    username = request.headers.get("REMOTE-USER")
    if not username:
        record_access(
            AUTH_FAILURE, outcome=FAILURE, detail="missing REMOTE-USER header"
        )
        raise AuthError("Missing REMOTE-USER header")
    return username


def get_current_user(
    username: str = Depends(_current_username),
    cursor=Depends(get_cursor),
) -> User:
    """Resolves the acting user, with role_name + permissions already joined in by crud.users."""
    user = _find_by_username(cursor, username)
    if user is None:
        record_access(
            AUTH_FAILURE,
            outcome=FAILURE,
            actor_username=username,
            detail="unknown user",
        )
        raise AuthError(f"Unknown user '{username}'")
    if not user.is_active:
        record_access(
            AUTH_FAILURE,
            outcome=FAILURE,
            actor_username=username,
            detail="inactive user",
        )
        raise AuthError(f"User '{username}' is inactive")

    structlog.contextvars.bind_contextvars(actor_id=user.id, actor_role=user.role_name)
    return user


def require_permission(permission: str):
    """Dependency factory: require_permission('user:view')."""

    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if permission not in current_user.permissions:
            log.warning(
                "permission_denied",
                required=permission,
                granted=current_user.permissions,
            )
            # One denial is somebody clicking the wrong thing; fifteen in
            # a minute across different resources is enumeration, and
            # that is only visible if each one is recorded.
            record_access(
                DENIED,
                outcome=DENIED,
                actor=current_user,
                resource_type="permission",
                resource_id=permission,
            )
            raise PermissionDeniedError(
                f"Permission '{permission}' is required for this operation"
            )
        return current_user

    return dependency
