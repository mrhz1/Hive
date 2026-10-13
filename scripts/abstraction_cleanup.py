"""Delete abstraction folders whose time is up.

Run it as a scheduled Cloudera Job (e.g. daily). An expired folder's copy
is removed from disk; its record stays, so its owner can make it again.

    python scripts/abstraction_cleanup.py
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
        if (candidate / "app" / "abstraction.py").is_file():
            return candidate
    raise RuntimeError("Cannot locate the repo root; set HIVE_REPO_ROOT")


sys.path.insert(0, str(_repo_root()))

from app import abstraction  # noqa: E402
from app.db import hive_cursor  # noqa: E402
from app.logging_setup import configure_logging  # noqa: E402


def main() -> int:
    configure_logging()
    with hive_cursor() as cursor:
        expired = abstraction.expire_due(cursor)
    print(f"{len(expired)} folder(s) expired")
    for folder in expired:
        print(f"  {folder.name} ({folder.id})")
    return 0


if __name__ == "__main__":
    # Under Cloudera's ipykernel launcher any SystemExit -- even 0 -- marks
    # the Job run failed, so only exit explicitly from a terminal.
    _rc = main()
    if "ipykernel" not in sys.modules:
        sys.exit(_rc)
