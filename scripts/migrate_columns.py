"""Add columns that sql/schema.sql has gained since a database was built."""
import argparse
import os
import sys
from pathlib import Path


def _repo_root():
    here = globals().get("__file__")
    candidates = []
    if here:
        own = Path(here).resolve().parent
        candidates += [own, own.parent]
    for var in ("HIVE_REPO_ROOT", "CDSW_PROJECT_DIR"):
        if os.environ.get(var):
            candidates.append(Path(os.environ[var]))
    cwd = Path.cwd().resolve()
    candidates += [cwd, cwd.parent]
    for candidate in candidates:
        if (candidate / "app" / "db.py").is_file():
            return candidate
    raise RuntimeError("Cannot locate the repo root; set HIVE_REPO_ROOT")


sys.path.insert(0, str(_repo_root()))

from app.db import hive_cursor  # noqa: E402

MIGRATIONS = (
    ("patient_application_files", "review_status", "STRING"),
    ("patient_application_files", "review_note", "STRING"),
    ("patient_applications", "status_reason", "STRING"),
    ("patient_applications", "assigned_to_id", "STRING"),
    ("patient_applications", "original_file_path", "STRING"),
)


def existing_columns(cursor, table: str):
    cursor.execute(f"DESCRIBE `{table}`")
    names = set()
    for row in cursor.fetchall():
        name = (row[0] or "").strip()
        if name and not name.startswith("#"):
            names.add(name.lower())
    return names


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Actually run the ALTERs")
    parser.add_argument("--list", action="store_true", help="Show what is missing")
    args = parser.parse_args(argv)

    with hive_cursor() as cursor:
        present = {}
        for table, _, _ in MIGRATIONS:
            if table not in present:
                present[table] = existing_columns(cursor, table)

        missing = [
            (table, column, kind)
            for table, column, kind in MIGRATIONS
            if column.lower() not in present[table]
        ]

        if not missing:
            print("Every column is already there; nothing to do.")
            return 0

        for table, column, kind in missing:
            print(f"missing: {table}.{column} {kind}")

        if not args.apply:
            print("\nRe-run with --apply to add them.")
            return 0

        for table, column, kind in missing:
            statement = (
                f"ALTER TABLE `{table}` ADD COLUMNS (`{column}` {kind})"
            )
            print(f"running: {statement}")
            cursor.execute(statement)

        print(f"\ndone -- added {len(missing)} column(s)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
