"""Remind ALERT_EMAIL_TO that a breach report is due (protocol section 4).

Run it hourly as a scheduled Cloudera Job. For every open incident it emails
once when the preliminary report (24 h after detection) or the full report
(72 h) is due within 6 hours or overdue, unless it is marked as sent.

    python scripts/incident_reminders.py
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
        if (candidate / "app" / "incidents.py").is_file():
            return candidate
    raise RuntimeError("Cannot locate the repo root; set HIVE_REPO_ROOT")


sys.path.insert(0, str(_repo_root()))

from app import incidents  # noqa: E402
from app.db import hive_cursor  # noqa: E402
from app.logging_setup import configure_logging  # noqa: E402


def main() -> int:
    configure_logging()
    with hive_cursor() as cursor:
        sent = incidents.due_reminders(cursor)
    print(f"{len(sent)} reminder(s) sent")
    return 0


if __name__ == "__main__":
    # Under Cloudera's ipykernel launcher any SystemExit -- even 0 -- marks
    # the Job run failed, so only exit explicitly from a terminal.
    _rc = main()
    if "ipykernel" not in sys.modules:
        sys.exit(_rc)
