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
        if (candidate / "app" / "incidents.py").is_file():
            return candidate
    raise RuntimeError("Cannot locate the repo root; set HIVE_REPO_ROOT")


sys.path.insert(0, str(_repo_root()))

from app import incidents
from app.db import hive_cursor
from app.logging_setup import configure_logging


def main() -> int:
    configure_logging()
    with hive_cursor() as cursor:
        sent = incidents.due_reminders(cursor)
    print(f"{len(sent)} reminder(s) sent")
    return 0


if __name__ == "__main__":
    _rc = main()
    if "ipykernel" not in sys.modules:
        sys.exit(_rc)
