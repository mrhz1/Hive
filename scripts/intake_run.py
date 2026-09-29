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
    if result["outcome"] != intake_run.RAN:
        print(f"{result['outcome']}: {result['detail']}")
        return

    print(
        f"swept {result['swept']} new file(s): {result['skipped']} skipped, "
        f"{result['conflicts']} in conflict"
    )
    print(f"redacted {result['redacted']}, failed {result['failed']}")
    if result["skipped"] or result["conflicts"] or result["failed"]:
        print("-> see the Intake page for what needs a person")


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
        description="De-identify files that have finished arriving in the intake folder.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Keep checking instead of checking once.",
    )
    parser.add_argument(
        "--every",
        type=float,
        default=60,
        help="Seconds between checks with --watch (default 60).",
    )
    parser.add_argument(
        "--shards",
        default=None,
        help="This process's shards, e.g. 0-3 or 0,4,8 (default: all).",
    )
    parser.add_argument(
        "--of",
        type=int,
        default=1,
        help="How many shards the work is split into across all processes.",
    )
    parser.add_argument(
        "--root",
        default=None,
        help="The drop folder (default: $INTAKE_DIR).",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).expanduser().resolve() if args.root else intake.intake_root()
    shards = _parse_shards(args.shards, args.of)
    root.mkdir(parents=True, exist_ok=True)

    if args.watch:
        print(f"watching {root} every {args.every:g}s (Ctrl-C to stop)")
        try:
            intake_run.watch(root, every_seconds=args.every, shards=shards, of=args.of)
        except KeyboardInterrupt:
            print("\nstopped")
        return 0

    _say(intake_run.run_once(root, shards=shards, of=args.of))
    return 0


if __name__ == "__main__":
    sys.exit(main())
