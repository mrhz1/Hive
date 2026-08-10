"""Add newly-introduced permissions to roles that already exist."""
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
        if (candidate / "app" / "security.py").is_file():
            return candidate
    raise RuntimeError("Cannot locate the repo root; set HIVE_REPO_ROOT")


sys.path.insert(0, str(_repo_root()))

from app.crud import roles as roles_crud  # noqa: E402
from app.db import hive_cursor  # noqa: E402
from app.schemas import RoleUpdate  # noqa: E402
from app.security import KNOWN_PERMISSIONS  # noqa: E402


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", help="Role name, e.g. admin")
    parser.add_argument(
        "--grant", help="Comma-separated permissions to add, e.g. files:read,files:upload"
    )
    parser.add_argument(
        "--all-missing",
        action="store_true",
        help="Add every permission the API knows that this role lacks",
    )
    parser.add_argument(
        "--list", action="store_true", help="Show each role and what it is missing"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Say what would change, change nothing"
    )
    return parser.parse_args(argv)


def show(cursor) -> int:
    for role in roles_crud.list_roles(cursor):
        missing = sorted(KNOWN_PERMISSIONS - set(role.permissions))
        print(f"\n{role.name} ({len(role.permissions)} granted)")
        print(f"  missing: {', '.join(missing) if missing else '(nothing)'}")
    return 0


def main(argv=None) -> int:
    args = parse_args(argv)

    with hive_cursor() as cursor:
        if args.list or not args.role:
            return show(cursor)

        role = next(
            (r for r in roles_crud.list_roles(cursor) if r.name == args.role), None
        )
        if role is None:
            print(f"No role named '{args.role}'", file=sys.stderr)
            return 1

        if args.all_missing:
            wanted = set(KNOWN_PERMISSIONS)
        elif args.grant:
            wanted = {p.strip() for p in args.grant.split(",") if p.strip()}
            unknown = wanted - KNOWN_PERMISSIONS
            if unknown:
                print(f"Unknown permissions: {', '.join(sorted(unknown))}", file=sys.stderr)
                return 1
        else:
            print("Nothing to do: pass --grant or --all-missing", file=sys.stderr)
            return 1

        added = sorted(wanted - set(role.permissions))
        if not added:
            print(f"'{role.name}' already has all of those")
            return 0

        print(f"{role.name}: adding {', '.join(added)}")
        if args.dry_run:
            print("(dry run, nothing written)")
            return 0

        roles_crud.update_role(
            cursor,
            role.id,
            RoleUpdate(permissions=sorted(set(role.permissions) | wanted)),
        )
        print(f"done -- {role.name} now has {len(set(role.permissions) | wanted)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
