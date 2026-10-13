"""Email the intake team when new files are waiting in the incoming folder.

Run it as a scheduled Cloudera Job (e.g. every 30 minutes). It mentions only
the files that arrived since its last email, so a quiet folder sends nothing.
Recipients: active users whose role has `deidentifier:notify`.

    python scripts/intake_notify.py
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
        if (candidate / "app" / "intake_notices.py").is_file():
            return candidate
    raise RuntimeError("Cannot locate the repo root; set HIVE_REPO_ROOT")


sys.path.insert(0, str(_repo_root()))

from app import intake_notices  # noqa: E402
from app.logging_setup import configure_logging  # noqa: E402


def main() -> int:
    configure_logging()
    result = intake_notices.notify_new_files()
    if not result["new"]:
        print("no new files")
    else:
        print(f"{result['new']} new file(s); email {'sent' if result['sent'] else 'NOT sent'}")
    return 0


if __name__ == "__main__":
    # Under Cloudera's ipykernel launcher any SystemExit -- even 0 -- marks
    # the Job run failed, so only exit explicitly from a terminal.
    _rc = main()
    if "ipykernel" not in sys.modules:
        sys.exit(_rc)
