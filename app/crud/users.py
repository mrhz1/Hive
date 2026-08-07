"""User CRUD, including the roles join that inlines role_name +
permissions onto every user read.
"""
import uuid
from typing import List, Optional

from app.crud.roles import _parse_permissions
from app.db import NOW_SQL, execute
from app.errors import ConflictError, NotFoundError, ValidationError
from app.logging_setup import get_logger
from app.schemas import User, UserCreate, UserUpdate

log = get_logger(__name__)

_BASE_COLS = (
    "`id`, `username`, `email`, `first_name`, `last_name`, "
    "`status`, `is_active`, `role_id`, `created_at`"
)

# LEFT JOIN so a user with no role (or a dangling role_id) still returns
# rather than vanishing from the result set.
_SELECT_WITH_ROLE = f"""
SELECT u.`id`, u.`username`, u.`email`, u.`first_name`, u.`last_name`,
       u.`status`, u.`is_active`, u.`role_id`, u.`created_at`,
       r.`name`, r.`permissions`
FROM `users` u
LEFT JOIN `roles` r ON u.`role_id` = r.`id`
"""


def _row_to_user(row) -> User:
    return User(
        id=row[0],
        username=row[1],
        email=row[2],
        first_name=row[3],
        last_name=row[4],
        status=row[5],
        is_active=bool(row[6]),
        role_id=row[7],
        created_at=row[8],
        role_name=row[9],
        permissions=_parse_permissions(row[10]),
    )


def get_user(cursor, user_id: str) -> Optional[User]:
    execute(cursor, _SELECT_WITH_ROLE + " WHERE u.`id` = %s", (user_id,))
    row = cursor.fetchone()
    return _row_to_user(row) if row else None


def get_user_or_404(cursor, user_id: str) -> User:
    user = get_user(cursor, user_id)
    if user is None:
        raise NotFoundError(f"User '{user_id}' not found")
    return user


def list_users(cursor) -> List[User]:
    execute(cursor, _SELECT_WITH_ROLE)
    return [_row_to_user(r) for r in cursor.fetchall()]


def _find_by_username(cursor, username: str) -> Optional[User]:
    """The whole user, role joined in -- not just their id.

    This is how the authenticated principal is resolved (see
    security.get_current_user): REMOTE-USER names a username, and the
    permission check that follows needs the role's grants, so fetching
    only the id would cost a second round trip to Hive for the rest.
    """
    execute(cursor, _SELECT_WITH_ROLE + " WHERE u.`username` = %s", (username,))
    row = cursor.fetchone()
    return _row_to_user(row) if row else None


def _find_by_email(cursor, email: str) -> Optional[str]:
    execute(cursor, "SELECT `id` FROM `users` WHERE `email` = %s", (email,))
    row = cursor.fetchone()
    return row[0] if row else None


def _assert_role_exists(cursor, role_id: Optional[str]) -> None:
    if role_id is None:
        return
    execute(cursor, "SELECT `id` FROM `roles` WHERE `id` = %s", (role_id,))
    if cursor.fetchone() is None:
        raise ValidationError(f"Role '{role_id}' does not exist")


def create_user(cursor, payload: UserCreate) -> User:
    # Hive has no UNIQUE constraint, so uniqueness is enforced by
    # pre-check SELECTs. Read-then-write is not atomic: concurrent creates
    # of the same username/email can both pass.
    if _find_by_username(cursor, payload.username):
        raise ConflictError(f"Username '{payload.username}' already exists")
    if _find_by_email(cursor, payload.email):
        raise ConflictError(f"Email '{payload.email}' already exists")
    _assert_role_exists(cursor, payload.role_id)

    user_id = str(uuid.uuid4())
    # _BASE_COLS ends with created_at, which is written as SQL text rather
    # than bound (see db.NOW_SQL) -- hence eight placeholders for nine
    # columns.
    execute(
        cursor,
        f"INSERT INTO `users` ({_BASE_COLS}) "
        f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s, {NOW_SQL})",
        (
            user_id,
            payload.username,
            payload.email,
            payload.first_name,
            payload.last_name,
            payload.status,
            payload.is_active,
            payload.role_id,
        ),
    )
    log.info("user_created", user_id=user_id, username=payload.username)
    return get_user_or_404(cursor, user_id)


def update_user(cursor, user_id: str, payload: UserUpdate) -> User:
    existing = get_user_or_404(cursor, user_id)

    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        return existing

    if "username" in fields and fields["username"] != existing.username:
        clash = _find_by_username(cursor, fields["username"])
        if clash and clash.id != user_id:
            raise ConflictError(f"Username '{fields['username']}' already exists")
    if "email" in fields and fields["email"] != existing.email:
        clash = _find_by_email(cursor, fields["email"])
        if clash and clash != user_id:
            raise ConflictError(f"Email '{fields['email']}' already exists")
    if "role_id" in fields:
        _assert_role_exists(cursor, fields["role_id"])

    set_clause = ", ".join(f"`{col}` = %s" for col in fields)
    params = tuple(fields.values()) + (user_id,)
    execute(cursor, f"UPDATE `users` SET {set_clause} WHERE `id` = %s", params)
    log.info("user_updated", user_id=user_id, fields=sorted(fields))
    return get_user_or_404(cursor, user_id)


def delete_user(cursor, user_id: str) -> User:
    existing = get_user_or_404(cursor, user_id)
    execute(cursor, "DELETE FROM `users` WHERE `id` = %s", (user_id,))
    log.info("user_deleted", user_id=user_id)
    return existing
