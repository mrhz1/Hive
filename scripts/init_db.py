"""Apply sql/schema.sql and load seed fixtures. Run with: make init

NOTE: INSERT ... VALUES issues one small ORC file per statement and is
slow -- it's fine for seeding a handful of fixture rows here, but do not
copy this pattern into application code that writes real volumes of data
(use INSERT ... SELECT / batch loads instead).
"""
import os
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from impala.dbapi import connect

load_dotenv(".env.local")

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "sql" / "schema.sql"

ALL_PERMISSIONS = [
    f"{model}:{action}"
    for model in ("users", "customers", "roles", "logs")
    for action in ("read", "create", "update", "delete")
]
READONLY_PERMISSIONS = [f"{model}:read" for model in ("users", "customers", "roles", "logs")]

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
    # Hive rejects a bound parameter for a whole ARRAY column, so array()
    # gets one placeholder per element; the values stay parameterised.
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
    base = datetime(2026, 7, 1, 12, 0, 0)
    rows = [
        (ADMIN_USER_ID, "admin", "admin@example.com", "Ada", "Admin",
         "active", True, ADMIN_ROLE_ID, base),
        (VIEWER_USER_ID, "viewer", "viewer@example.com", "Vic", "Viewer",
         "active", True, VIEWER_ROLE_ID, base),
    ]
    rows += [
        (
            str(uuid.uuid4()),
            f"user{i}",
            f"user{i}@example.com",
            f"First{i}",
            f"Last{i}",
            "active" if i % 5 != 0 else "inactive",
            i % 5 != 0,
            VIEWER_ROLE_ID,
            base + timedelta(days=i),
        )
        for i in range(1, 19)
    ]
    for row in rows:
        cursor.execute(
            "INSERT INTO `users` (`id`, `username`, `email`, `first_name`, "
            "`last_name`, `status`, `is_active`, `role_id`, `created_at`) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            row,
        )
    print(f"seeded {len(rows)} rows into users")


def seed_customers(cursor) -> None:
    base = datetime(2026, 7, 1, 12, 0, 0)
    rows = [
        (
            str(uuid.uuid4()),
            f"customer{i}@example.com",
            f"Cust{i}",
            f"Last{i}",
            f"+1555000{i:04d}",
            f"{i} Main St",
            "active" if i % 4 != 0 else "inactive",
            i % 4 != 0,
            base + timedelta(days=i),
        )
        for i in range(1, 11)
    ]
    for row in rows:
        cursor.execute(
            "INSERT INTO `customers` (`id`, `email`, `first_name`, `last_name`, "
            "`phone_number`, `address`, `status`, `is_active`, `created_at`) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            row,
        )
    print(f"seeded {len(rows)} rows into customers")


def main() -> int:
    try:
        conn = connect_from_env()
    except Exception as exc:
        print(f"FAILED to connect to hive -- {exc}", file=sys.stderr)
        return 1

    try:
        cursor = conn.cursor()
        apply_schema(cursor)
        seed_roles(cursor)
        seed_users(cursor)
        seed_customers(cursor)
    except Exception as exc:
        print(f"FAILED during init -- {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    print("\ninit_db complete. Use these ids as the X-User-Id header:")
    print(f"  admin  (all permissions):  {ADMIN_USER_ID}")
    print(f"  viewer (read-only):        {VIEWER_USER_ID}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
