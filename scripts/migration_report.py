"""Write the migration report: how far the intake has got and what still
needs a person (app/migration_report.py). Run it any time during a big
migration as a progress check, and at the end. Reads only folders and the
database; no document is opened.

    python scripts/migration_report.py
    python scripts/migration_report.py --out /path/to/reports --cap 100000
"""

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
        if (candidate / "app" / "reports.py").is_file():
            return candidate
    raise RuntimeError("Cannot locate the repo root; set HIVE_REPO_ROOT")


sys.path.insert(0, str(_repo_root()))

import argparse  # noqa: E402

from app import migration_report  # noqa: E402
from app.db import hive_cursor  # noqa: E402
from app.logging_setup import configure_logging  # noqa: E402
from app.reports import DEFAULT_CAP  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Write the migration report.")
    parser.add_argument("--out", help="Folder for the report (default REPORTS_DIR).")
    parser.add_argument("--cap", type=int, default=DEFAULT_CAP,
                        help="Rows per list in the workbook; the CSVs have them all.")
    args = parser.parse_args(argv)
    configure_logging()
    with hive_cursor() as cursor:
        path = migration_report.build(cursor, Path(args.out) if args.out else None, args.cap)
    print(f"report: {path}")
    return 0


if __name__ == "__main__":
    # Under Cloudera's ipykernel launcher any SystemExit -- even 0 -- marks
    # the Job run failed, so only exit explicitly from a terminal.
    _rc = main()
    if "ipykernel" not in sys.modules:
        sys.exit(_rc)
