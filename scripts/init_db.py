import os
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv
from impala.dbapi import connect

load_dotenv(".env.local")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.security import FILE_VIEW_PERMISSIONS, KNOWN_PERMISSIONS, MODEL_ACTIONS  # noqa: E402

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "sql" / "schema.sql"

ALL_PERMISSIONS = sorted(KNOWN_PERMISSIONS)

READONLY_PERMISSIONS = [
    f"{model}:{'read' if 'read' in actions else 'view'}"
    for model, actions in MODEL_ACTIONS.items()
    if model not in ("rejection", "deidentifier")  # granted to specific roles only
] + list(FILE_VIEW_PERMISSIONS)

ADMIN_ROLE_ID = str(uuid.uuid4())
VIEWER_ROLE_ID = str(uuid.uuid4())
ADMIN_USER_ID = str(uuid.uuid4())
VIEWER_USER_ID = str(uuid.uuid4())


def connect_from_env():
    return connect(
        host=os.environ["HIVE_HOST"],
        port=int(os.environ["HIVE_PORT"]),
        database=os.environ["HIVE_DB"],
        auth_mechanism=os.environ["HIVE_AUTH"],
        user=os.environ["HIVE_USER"],
    )


def apply_schema(cursor) -> None:
    raw = SCHEMA_PATH.read_text()
    no_comments = "\n".join(
        line for line in raw.splitlines() if not line.strip().startswith("--")
    )
    statements = [s.strip() for s in no_comments.split(";") if s.strip()]
    for stmt in statements:
        cursor.execute(stmt)
        print(f"applied: {stmt.splitlines()[0]}...")


def seed_roles(cursor) -> None:
    for role_id, name, perms in (
        (ADMIN_ROLE_ID, "admin", ALL_PERMISSIONS),
        (VIEWER_ROLE_ID, "viewer", READONLY_PERMISSIONS),
    ):
        placeholders = ", ".join(["%s"] * len(perms))
        cursor.execute(
            "INSERT INTO `roles` (`id`, `name`, `permissions`) "
            f"SELECT %s, %s, array({placeholders})",
            (role_id, name) + tuple(perms),
        )
    print("seeded 2 roles (admin, viewer)")


def seed_users(cursor) -> None:
    rows = [
        (ADMIN_USER_ID, "admin", "admin@example.com", "Ada", "Admin",
         "active", True, ADMIN_ROLE_ID),
        (VIEWER_USER_ID, "viewer", "viewer@example.com", "Vic", "Viewer",
         "active", True, VIEWER_ROLE_ID),
    ]
    for row in rows:
        cursor.execute(
            "INSERT INTO `users` (`id`, `username`, `email`, `first_name`, "
            "`last_name`, `status`, `is_active`, `role_id`, `created_at`) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, current_timestamp())",
            row,
        )
    print(f"seeded {len(rows)} rows into users")


def main() -> int:
    try:
        conn = connect_from_env()
    except Exception as exc:
        print(f"FAILED to connect to hive: {exc}", file=sys.stderr)
        return 1

    try:
        cursor = conn.cursor()
        apply_schema(cursor)
        seed_roles(cursor)
        seed_users(cursor)
    except Exception as exc:
        print(f"FAILED during init: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    print("\ninit_db complete. Use these usernames as the REMOTE-USER header:")
    print(f"  admin  (all permissions):  admin   (id {ADMIN_USER_ID})")
    print(f"  viewer (read-only):        viewer  (id {VIEWER_USER_ID})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
