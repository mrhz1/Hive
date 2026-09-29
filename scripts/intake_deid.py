"""Redact everything a sweep queued, several files at a time.

    python scripts/intake_deid.py                 # drain the queue
    python scripts/intake_deid.py --workers 4     # four at once
    python scripts/intake_deid.py --limit 1       # one file, to try it out

Run `scripts/intake_sweep.py --apply` first: this drains what that queued,
and does not go looking at the folder itself.

Sizing, measured on this pipeline: 19-31 seconds per page on a 4-core job.
So a ten-page document is about four minutes, and a thousand of them is
around 67 hours in one lane -- which is what --workers is for. The ceiling
is memory, not cores: a worker killed for running out of it (exit -9)
produces nothing, so raise DEID_WORKERS against measured peak usage and set
DEID_WORKER_CPU_THREADS so N workers do not each help themselves to eight
cores.
"""

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
        if (candidate / "app" / "intake_worker.py").is_file():
            return candidate
    raise RuntimeError("Cannot locate the repo root; set HIVE_REPO_ROOT")


sys.path.insert(0, str(_repo_root()))

from app.logging_setup import configure_logging  # noqa: E402

from app import intake_worker  # noqa: E402
from app.crud import intake_files as crud  # noqa: E402
from app.db import hive_cursor  # noqa: E402


def main(argv=None) -> int:
    configure_logging()

    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Files to redact at once (default: $DEID_WORKERS, or 1).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Stop after this many files. Useful for a first run.",
    )
    args = parser.parse_args(argv)

    if args.workers:
        os.environ["DEID_WORKERS"] = str(args.workers)

    with hive_cursor() as cursor:
        before = crud.counts(cursor)

    if not before.queued:
        print("Nothing is queued.")
        print("\nRun `python scripts/intake_sweep.py --apply` first.")
        return 0

    pool = intake_worker.safe_worker_count()
    print(f"{before.queued} file(s) queued; {pool} worker(s)")

    threads = intake_worker.worker_cpu_threads()
    if threads:
        print(f"each worker limited to {threads} core(s)")
    elif pool > 1:
        print(
            "DEID_WORKER_CPU_THREADS is unset, so every worker will use the "
            "pipeline's default of 8 cores."
        )

    result = intake_worker.drain(limit=args.limit)

    with hive_cursor() as cursor:
        after = crud.counts(cursor)

    print(
        f"\nredacted {result['done']}, failed {result['failed']} "
        f"of {result['claimed']} claimed"
    )
    print(
        f"queue now: {after.queued} queued, {after.done} done, "
        f"{after.failed} failed, {after.conflict} in conflict, "
        f"{after.skipped} skipped"
    )

    if after.failed:
        with hive_cursor() as cursor:
            for row in crud.list_files(cursor, status="failed"):
                print(f"  failed: {row.relative_path} -- {row.detail or 'no detail'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
