"""Delete researcher Cloudera AI projects whose access has expired.

Run as a scheduled job with "Run as" set to the service account, in the same
admin-only project as the Hive API (see DEPLOYMENT.md).
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
        if (candidate / "app" / "cai_projects.py").is_file():
            return candidate
    raise RuntimeError("Cannot locate the repo root; set HIVE_REPO_ROOT")


sys.path.insert(0, str(_repo_root()))

from app import cai_projects
from app.audit import record_audit
from app.db import hive_cursor
from app.logging_setup import configure_logging


def main() -> int:
    configure_logging()
    with hive_cursor() as cursor:
        expired = cai_projects.expire_due(cursor)
    print(f"{len(expired)} researcher project(s) expired")
    for record in expired:
        print(f"  {record.cai_username} {record.cai_project_id}")
        record_audit(
            action="DELETE",
            entity_type="cai_project",
            entity_id=record.id,
            user_id="cai-cleanup",
            new_values={"cai_project_id": record.cai_project_id, "reason": "access expired"},
        )
    return 0


if __name__ == "__main__":
    _rc = main()
    if "ipykernel" not in sys.modules:
        sys.exit(_rc)
