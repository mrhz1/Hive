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

from app.logging_setup import configure_logging  # noqa: E402

from app import intake  # noqa: E402


def _column(rows, index):
    return max((len(str(r[index])) for r in rows), default=0)


def _table(rows, headers):
    widths = [max(len(h), _column(rows, i)) for i, h in enumerate(headers)]
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    print(f"  {line}")
    print(f"  {'  '.join('-' * w for w in widths)}")
    for row in rows:
        print(f"  {'  '.join(str(v).ljust(widths[i]) for i, v in enumerate(row))}")


def _report(result, root: Path, settle_seconds: float) -> None:
    total = len(result.candidates)
    print(f"\nintake root: {root}")
    print(f"mirror:      {intake.deidentified_root(root)}")
    print(f"found:       {total} file(s)\n")

    if not total:
        print("Nothing to do. Drop a folder in and run this again.")
        return

    print(
        f"  queued    {len(result.queued):>5}   ready to de-identify\n"
        f"  skipped   {len(result.skipped):>5}   cannot be placed, fix at source\n"
        f"  conflicts {len(result.conflicts):>5}   two codes, needs a person"
    )

    unsettled = [
        c
        for c in result.queued
        if not intake.is_settled(c.path, settle_seconds)
    ]
    if unsettled:
        print(
            f"\n  {len(unsettled)} of those are still being written to and would "
            f"be left for the next sweep."
        )

    if result.queued:
        print("\nWould de-identify:")
        _table(
            [
                (c.code, c.extension, c.relative_path, _output_hint(c))
                for c in result.queued[:40]
            ],
            ("code", "type", "source", "would become"),
        )
        if len(result.queued) > 40:
            print(f"  ... and {len(result.queued) - 40} more")

    if result.conflicts:
        print("\nConflicts (need a manual choice):")
        _table(
            [
                (
                    c.detection.path_code,
                    c.detection.name_code,
                    c.relative_path,
                )
                for c in result.conflicts
            ],
            ("path says", "name says", "file"),
        )

    if result.skipped:
        print("\nSkipped:")
        _table(
            [(c.reason, c.relative_path, c.detail or "") for c in result.skipped],
            ("reason", "file", "detail"),
        )

    codes = sorted({c.code for c in result.queued if c.code})
    if codes:
        print(f"\n{len(codes)} patient code(s): {', '.join(codes[:20])}")
        if len(codes) > 20:
            print(f"  ... and {len(codes) - 20} more")


def _output_hint(candidate) -> str:
    directory = Path(candidate.relative_path).parent
    return str(directory / f"{candidate.code}_<date>_<serial>.{candidate.extension}")


def main(argv=None) -> int:
    configure_logging()

    parser = argparse.ArgumentParser(
        description="Check the intake folder and show what would be de-identified (dry run unless --apply).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--root",
        default=None,
        help="The folder to look at (default: $INTAKE_DIR).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Record the sweep in Hive. Still does not redact anything.",
    )
    parser.add_argument(
        "--settle-seconds",
        type=float,
        default=None,
        help=(
            "How long a file must have been untouched to count as finished "
            "arriving (default: $INTAKE_SETTLE_SECONDS, or 20)."
        ),
    )
    args = parser.parse_args(argv)

    root = Path(args.root).expanduser().resolve() if args.root else intake.intake_root()

    if not root.is_dir():
        print(f"No such folder: {root}")
        print("\nCreate it, or point --root (or $INTAKE_DIR) somewhere that exists.")
        return 1

    if not args.apply:
        result = intake.sweep(None, root=root, dry_run=True)
        _report(result, root, args.settle_seconds)
        print("\nThis was a dry run. Nothing was written. Re-run with --apply to record it.")
        return 0

    from app.db import hive_cursor

    with hive_cursor() as cursor:
        result = intake.sweep(cursor, root=root, dry_run=False)

    _report(result, root, args.settle_seconds)
    print(f"\nbatch {result.batch_id}")
    print(f"recorded {result.recorded} file(s); {result.already_seen} seen before")
    return 0


if __name__ == "__main__":
    sys.exit(main())
