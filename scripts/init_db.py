"""Apply sql/schema.sql and load seed fixtures. Run with: make init

NOTE: INSERT ... VALUES issues one small ORC file per statement and is
slow -- it's fine for seeding a handful of fixture rows here, but do not
copy this pattern into application code that writes real volumes of data
(use INSERT ... SELECT / batch loads instead).
"""
import os
import sys
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from impala.dbapi import connect

load_dotenv(".env.local")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.security import PERMISSION_ACTIONS, PERMISSION_MODELS  # noqa: E402

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "sql" / "schema.sql"

# Derived from app.security so the seeded grants cannot drift from the
# set the API actually enforces.
ALL_PERMISSIONS = [
    f"{model}:{action}"
    for model in PERMISSION_MODELS
    for action in PERMISSION_ACTIONS
]
READONLY_PERMISSIONS = [f"{model}:view" for model in PERMISSION_MODELS]

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


def seed_patients(cursor) -> None:
    """Seeds a subset of the patient columns.

    Deliberately not every column: the point is a usable fixture set, and
    the rest are nullable by design. The DATE columns need an explicit
    CAST -- Hive will not coerce a bound STRING into a DATE.
    """
    base = datetime(2026, 7, 1, 12, 0, 0)
    columns = (
        "id", "instcode", "pname", "pemail", "phone1", "wphone1",
        "street", "city", "state", "zip", "country",
        "fstname", "lstname", "ptemail", "ptphone", "ptwphone",
        "ptstreet", "ptcity", "ptstate", "ptzip", "ptcountry",
        "dt_reg", "dt_b", "status", "is_active", "created_at",
    )
    date_columns = {"dt_reg", "dt_b"}

    rows = [
        (
            str(uuid.uuid4()),
            f"INST{i:03d}",
            f"Springfield Clinic {i}",
            f"clinic{i}@example.com",
            f"+1555100{i:04d}",
            f"+1555200{i:04d}",
            f"{i} Medical Plaza",
            "Springfield",
            "IL",
            f"627{i:02d}",
            "US",
            f"Pat{i}",
            f"Last{i}",
            f"patient{i}@example.com",
            f"+1555300{i:04d}",
            f"+1555400{i:04d}",
            f"{i} Elm St",
            "Springfield",
            "IL",
            f"627{i:02d}",
            "US",
            (base + timedelta(days=i)).date().isoformat(),
            date(1960 + i, (i % 12) + 1, (i % 28) + 1).isoformat(),
            "active" if i % 4 != 0 else "inactive",
            i % 4 != 0,
            base + timedelta(days=i),
        )
        for i in range(1, 11)
    ]

    column_list = ", ".join(f"`{c}`" for c in columns)
    placeholders = ", ".join(
        "CAST(%s AS DATE)" if c in date_columns else "%s" for c in columns
    )
    for row in rows:
        cursor.execute(
            f"INSERT INTO `patients` ({column_list}) VALUES ({placeholders})",
            row,
        )
    print(f"seeded {len(rows)} rows into patients")


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
        seed_patients(cursor)
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
