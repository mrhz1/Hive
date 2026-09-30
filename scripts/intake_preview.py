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


def main(argv=None) -> int:
    configure_logging()

    parser = argparse.ArgumentParser(
        description="Show what a de-identification run would do with the intake folder. Nothing is moved."
    )
    parser.add_argument("--root", default=None, help="The incoming folder (default: $INTAKE_DIR).")
    parser.add_argument("--settle-seconds", type=float, default=None)
    args = parser.parse_args(argv)

    root = Path(args.root).expanduser().resolve() if args.root else intake.intake_root()
    overrides = intake.load_overrides()

    ready = []
    attention = []
    copying = 0
    for path in intake.walk(root):
        if not intake.is_settled(path, args.settle_seconds):
            copying += 1
            continue
        candidate = intake.classify(path, root, overrides)
        if candidate.reason:
            attention.append((candidate.reason, candidate.relative_path, candidate.detail or ""))
        else:
            ready.append((candidate.code, candidate.extension, candidate.relative_path))

    print(f"\nincoming:      {root}")
    print(f"de-identified: {intake.deidentified_root()}")
    print(f"\nready:           {len(ready)}")
    print(f"needs attention: {len(attention)}")
    print(f"still copying:   {copying}\n")

    if ready:
        print("Ready:")
        _table(ready[:40], ("code", "type", "file"))
        if len(ready) > 40:
            print(f"  ... and {len(ready) - 40} more")
    if attention:
        print("\nNeeds attention:")
        _table(attention[:40], ("reason", "file", "detail"))
        if len(attention) > 40:
            print(f"  ... and {len(attention) - 40} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
