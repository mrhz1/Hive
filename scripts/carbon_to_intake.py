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
        if (candidate / "app" / "intake.py").is_file():
            return candidate
    raise RuntimeError("Cannot locate the repo root; set HIVE_REPO_ROOT")


sys.path.insert(0, str(_repo_root()))

from app import carbon, intake


def main():
    parser = argparse.ArgumentParser(description="Copy files from the Carbon share into INTAKE_DIR")
    parser.add_argument("folders", nargs="+", help="folders inside the share, e.g. cardiac/2024")
    parser.add_argument("--apply", action="store_true", help="copy; without it only lists what would be copied")
    args = parser.parse_args()

    print(f"from   {carbon.share()}")
    print(f"to     {intake.intake_root()}")
    print("mode   " + ("COPY" if args.apply else "dry run (add --apply to copy)"))

    found = carbon.plan(args.folders)
    todo = found["todo"]
    print(
        f"\n{found['files']} new files ({found['bytes'] / 1024 / 1024:.1f} MB), "
        f"{found['skipped']} already in intake or processed"
    )
    if not args.apply:
        for _, relative, _ in todo[:20]:
            print(f"  {relative}")
        if len(todo) > 20:
            print(f"  ... and {len(todo) - 20} more")
        return

    smb = carbon.connect()
    failed = 0
    for number, (remote, relative, _) in enumerate(todo, 1):
        try:
            carbon.copy_file(smb, remote, intake.intake_root() / Path(*relative.parts))
            print(f"[{number}/{len(todo)}] OK    {relative}")
        except Exception as exc:
            failed += 1
            print(f"[{number}/{len(todo)}] FAIL  {relative}: {type(exc).__name__}: {exc}")
    print(f"\ncopied {len(todo) - failed}, failed {failed}. Start de-identification on the De-Identifier page.")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
