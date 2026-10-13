"""Correct redacted files' modality and date in bulk, and reject the ones
that still show an identifier (protocol 7.9).

The file is a spreadsheet (.xlsx or .csv) with the columns File, Modality,
Document date and Reject reason; see app/file_corrections.py. Without
--apply it only shows what it would do.

    python scripts/update_file_metadata.py corrections.xlsx
    python scripts/update_file_metadata.py corrections.xlsx --apply --user jsmith
"""

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
        if (candidate / "app" / "file_corrections.py").is_file():
            return candidate
    raise RuntimeError("Cannot locate the repo root; set HIVE_REPO_ROOT")


sys.path.insert(0, str(_repo_root()))

from app import file_corrections  # noqa: E402
from app.audit import record_audit  # noqa: E402
from app.db import hive_cursor  # noqa: E402
from app.errors import AppError  # noqa: E402
from app.logging_setup import configure_logging  # noqa: E402

SCRIPT_ACTOR = "metadata-script"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Bulk corrections to redacted files.")
    parser.add_argument("path", help="The corrections spreadsheet (.xlsx or .csv).")
    parser.add_argument("--apply", action="store_true", help="Make the changes.")
    parser.add_argument("--user", default=SCRIPT_ACTOR, help="Who to record in the audit log.")
    args = parser.parse_args(argv)
    configure_logging()

    path = Path(args.path)
    try:
        with hive_cursor() as cursor:
            rows = file_corrections.correct(cursor, path.name, path.read_bytes(), args.apply)
    except (AppError, OSError) as e:
        print(f"error: {e}")
        return 1

    for row in rows:
        detail = "; ".join(row.errors) if row.errors else (
            f"{row.old_name} -> {row.new_name}" if row.new_name != row.old_name else ""
        )
        print(f"line {row.line:>5}  {row.action:<14} {row.file}  {detail}")

    changed = [r for r in rows if r.action not in ("unchanged", "error")]
    errors = [r for r in rows if r.action == "error"]
    print(f"\n{len(changed)} to change, {len(errors)} with problems, "
          f"{len(rows) - len(changed) - len(errors)} unchanged")
    if not args.apply:
        print("nothing changed; run again with --apply")
        return 0

    record_audit(
        action="UPDATE",
        entity_type="file_corrections",
        entity_id=path.name,
        user_id=args.user,
        new_values={
            "changed": [
                {"file": r.old_name, "new_name": r.new_name, "action": r.action}
                for r in changed
            ],
            "errors": len(errors),
        },
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
