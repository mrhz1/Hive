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
# Only the roles that handle rejections see them.
MODEL_ACTIONS["rejection"] = ("view",)
# The De-Identifier page: seeing its status and lists, and running it.
MODEL_ACTIONS["deidentifier"] = ("view", "run")
# Research projects, and the Zone 2 safe copies made for them.
MODEL_ACTIONS["project"] = PERMISSION_ACTIONS
MODEL_ACTIONS["zone2"] = ("prepare", "review")
MODEL_ACTIONS["files"] = (
    "read",
    "upload",
    "download",
    "delete",
    "reject",
    "view_original",
    "view_deidentified",
    "metadata",
    "deid_metadata",
)

# Seeing a document is read-only; taking it away (download), rejecting or
# deleting it are granted separately.
FILE_VIEW_PERMISSIONS = (
    "files:view_original",
    "files:view_deidentified",
    "files:metadata",
    "files:deid_metadata",
)

KNOWN_PERMISSIONS = set()
for model, actions in MODEL_ACTIONS.items():
    for action in actions:
        KNOWN_PERMISSIONS.add(f"{model}:{action}")


def _current_username(request: Request) -> str:
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


def assert_permission(user: User, permission: str) -> User:
    if permission not in user.permissions:
        log.warning(
            "permission_denied",
            required=permission,
            granted=user.permissions,
        )
        record_access(
            DENIED,
            outcome=DENIED,
            actor=user,
            resource_type="permission",
            resource_id=permission,
        )
        raise PermissionDeniedError(
            f"Permission '{permission}' is required for this operation"
        )
    return user


def view_permission(deidentified: bool) -> str:
    return "files:view_deidentified" if deidentified else "files:view_original"


def metadata_permission(deidentified: bool) -> str:
    return "files:deid_metadata" if deidentified else "files:metadata"


def require_permission(permission: str):

    def dependency(current_user: User = Depends(get_current_user)) -> User:
        return assert_permission(current_user, permission)

    return dependency
