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
        if (candidate / "app" / "intake_run.py").is_file():
            return candidate
    raise RuntimeError("Cannot locate the repo root; set HIVE_REPO_ROOT")


sys.path.insert(0, str(_repo_root()))

from app.logging_setup import configure_logging  # noqa: E402

from app import intake, intake_run  # noqa: E402


def _say(result) -> None:
    if result["outcome"] != "ran":
        print(f"{result['outcome']}: {result['detail']}")
        return
    print(f"de-identified {result['done']}, failed {result['failed']}, set aside {result['set_aside']}")
    if result["skipped_unsettled"]:
        print(f"{result['skipped_unsettled']} file(s) still being copied, run again later")
    if result["failed"] or result["set_aside"]:
        print("-> see the Intake page for the files that need attention")


def _parse_shards(text, of):
    if not text:
        return None
    shards = set()
    for part in text.split(","):
        if "-" in part:
            low, high = part.split("-", 1)
            shards.update(range(int(low), int(high) + 1))
        else:
            shards.add(int(part))
    bad = [k for k in shards if not 0 <= k < of]
    if bad:
        raise SystemExit(f"shards {sorted(bad)} are outside 0..{of - 1}")
    return sorted(shards)


def main(argv=None) -> int:
    configure_logging()

    parser = argparse.ArgumentParser(
        description="De-identify every file in the intake folder."
    )
    parser.add_argument("--limit", type=int, default=None, help="Stop after this many files.")
    parser.add_argument("--workers", type=int, default=None, help="Files at once (default: $DEID_WORKERS).")
    parser.add_argument("--shards", default=None, help="This process's shards, e.g. 0-3 or 0,4,8 (default: all).")
    parser.add_argument("--of", type=int, default=1, help="Total number of shards across all processes.")
    parser.add_argument("--root", default=None, help="The incoming folder (default: $INTAKE_DIR).")
    args = parser.parse_args(argv)

    root = Path(args.root).expanduser().resolve() if args.root else intake.intake_root()
    shards = _parse_shards(args.shards, args.of)

    _say(intake_run.run(limit=args.limit, pool_size=args.workers, shards=shards, of=args.of, root=root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
