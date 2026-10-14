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

import argparse

from app import qc
from app.db import hive_cursor
from app.logging_setup import configure_logging


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the data quality check.")
    parser.add_argument("--out", help="Folder for the report (default REPORTS_DIR).")
    parser.add_argument("--no-email", action="store_true", help="Don't send the email.")
    args = parser.parse_args(argv)
    configure_logging()
    with hive_cursor() as cursor:
        path = qc.run(cursor, Path(args.out) if args.out else None, email=not args.no_email)
    print(f"report: {path}")
    return 0


if __name__ == "__main__":
    _rc = main()
    if "ipykernel" not in sys.modules:
        sys.exit(_rc)
