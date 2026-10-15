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
        if (candidate / "app" / "permissions.py").is_file():
            return candidate
    raise RuntimeError("Cannot locate the repo root; set HIVE_REPO_ROOT")


sys.path.insert(0, str(_repo_root()))

from app.crud import projects as projects_crud
from app.crud import roles as roles_crud
from app.db import execute, hive_cursor
from app.permissions import KNOWN_PERMISSIONS, RETIRED_PERMISSIONS
from app.schemas import RoleUpdate

CARRIED_OVER = {
    "abstraction:delete": ("abstraction:manage",),
    "project:update": ("project:workspace",),
}

ADMIN_MARKER = "role:update"
ADMIN_EXTRAS = (
    "abstraction:manage",
    "files:grant_original",
    "project:manage",
    "project:workspace",
)


def stored_roles(cursor):
    execute(cursor, "SELECT `id`, `name`, `permissions` FROM `roles`")
    return [
        (row[0], row[1], set(roles_crud.parse_stored_permissions(row[2]))) for row in cursor.fetchall()
    ]


def upgraded(stored: set) -> set:
    result = {p for p in stored if p in KNOWN_PERMISSIONS}
    for old, new in CARRIED_OVER.items():
        if old in stored:
            result.update(new)
    if ADMIN_MARKER in stored:
        result.update(ADMIN_EXTRAS)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Bring stored roles and projects up to the current permission list"
    )
    parser.add_argument("--apply", action="store_true", help="Write the changes")
    args = parser.parse_args(argv)

    changes = 0
    with hive_cursor() as cursor:
        for role_id, name, stored in stored_roles(cursor):
            after = upgraded(stored)
            added = sorted(after - stored)
            removed = sorted(stored - after)
            if not added and not removed:
                continue
            changes += 1
            print(f"role {name}:")
            if added:
                print(f"  add    {', '.join(added)}")
            if removed:
                retired = [p for p in removed if p in RETIRED_PERMISSIONS]
                other = [p for p in removed if p not in RETIRED_PERMISSIONS]
                if retired:
                    print(f"  retire {', '.join(retired)}")
                if other:
                    print(f"  drop   {', '.join(other)} (no longer exist)")
            if args.apply:
                roles_crud.update_role(cursor, role_id, RoleUpdate(permissions=sorted(after)))

        for project in projects_crud.list_projects(cursor):
            if not project.created_by_id:
                continue
            if projects_crud.is_member(cursor, project.id, project.created_by_id):
                continue
            changes += 1
            print(f"project {project.short_code}: add its creator as a member")
            if args.apply:
                projects_crud.add_member(
                    cursor, project.id, project.created_by_id, project.created_by_id
                )

    if not changes:
        print("Every role and project is up to date; nothing to do.")
    elif not args.apply:
        print("\nRe-run with --apply to write these changes.")
    else:
        print(f"\ndone, {changes} change(s) written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
