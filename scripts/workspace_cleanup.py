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
        if (candidate / "app" / "workspace.py").is_file():
            return candidate
    raise RuntimeError("Cannot locate the repo root; set HIVE_REPO_ROOT")


sys.path.insert(0, str(_repo_root()))

from app import workspace
from app.audit import record_audit
from app.db import hive_cursor
from app.logging_setup import configure_logging


def main() -> int:
    configure_logging()
    with hive_cursor() as cursor:
        expired = workspace.expire_due(cursor)
    print(f"{len(expired)} workspace(s) expired")
    for project in expired:
        print(f"  {project.short_code} {project.name}")
        record_audit(
            action="UPDATE",
            entity_type="project",
            entity_id=project.id,
            user_id="workspace-cleanup",
            new_values={"workspace": "expired"},
        )
    return 0


if __name__ == "__main__":
    _rc = main()
    if "ipykernel" not in sys.modules:
        sys.exit(_rc)
