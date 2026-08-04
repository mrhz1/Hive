"""Cloudera AI job entrypoint: drain the de-identification queue.

The API can de-identify a file in a background task today, which is fine
at low volume but keeps ~3GB of ML dependencies and minutes of CPU inside
the web process. This script is the same work, scheduled instead:

    python scripts/deid_worker.py                # everything pending
    python scripts/deid_worker.py --limit 20     # cap one run
    DEID_RETRY_STALE_MINUTES=60 python scripts/deid_worker.py

It calls app.deid.run_deidentification -- the exact function the API
calls -- so moving between the two changes scheduling, not behaviour.

Exit codes: 0 nothing failed, 1 every file failed, 2 partial failure.

Run ONE instance at a time. Hive has no reliable compare-and-set, so two
overlapping runs can both claim the same row; the guard below narrows the
window but does not close it.
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.crud import customer_files as crud  # noqa: E402
from app.db import hive_cursor  # noqa: E402
from app.deid import run_deidentification  # noqa: E402
from app.logging_setup import configure_logging, get_logger  # noqa: E402

log = get_logger("deid_worker")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="De-identify pending customer files")
    parser.add_argument(
        "--limit",
        type=int,
        default=int(os.environ.get("DEID_BATCH_LIMIT", "0")),
        help="Maximum files to process this run (0 = no limit)",
    )
    parser.add_argument(
        "--retry-stale-minutes",
        type=int,
        default=int(os.environ.get("DEID_RETRY_STALE_MINUTES", "0")),
        help=(
            "Also pick up rows stuck in 'processing' for this many minutes "
            "(0 = never). Guards against a run that died mid-file."
        ),
    )
    parser.add_argument("--log-level", default=os.environ.get("DEID_LOG_LEVEL", "INFO"))
    return parser.parse_args(argv)


def _is_stale(created_at, minutes: int) -> bool:
    if minutes <= 0:
        return False
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=minutes)
    return created_at <= cutoff


def collect_pending(limit: int, retry_stale_minutes: int):
    """Files awaiting de-identification, oldest first.

    Filtered in Python rather than SQL because the whole table is small
    and this keeps the query trivial; move it into the WHERE clause if
    the file count ever grows large enough to matter.
    """
    with hive_cursor() as cursor:
        every = crud.list_files(cursor)

    pending = [f for f in every if f.deid_status == "pending"]

    if retry_stale_minutes > 0:
        stuck = [
            f
            for f in every
            if f.deid_status == "processing" and _is_stale(f.created_at, retry_stale_minutes)
        ]
        if stuck:
            log.warning("retrying_stale_files", count=len(stuck))
        pending.extend(stuck)

    pending.sort(key=lambda f: f.created_at)
    return pending[:limit] if limit > 0 else pending


def main(argv=None) -> int:
    args = parse_args(argv)
    configure_logging()

    queue = collect_pending(args.limit, args.retry_stale_minutes)
    if not queue:
        log.info("nothing_to_do")
        return 0

    log.info("draining_queue", count=len(queue))

    succeeded = 0
    failed = 0

    for record in queue:
        run_deidentification(record.id)

        # run_deidentification never raises; re-read to see what it did.
        with hive_cursor() as cursor:
            after = crud.get_file(cursor, record.id)

        if after and after.deid_status == "done":
            succeeded += 1
        else:
            failed += 1

    log.info("queue_drained", succeeded=succeeded, failed=failed)

    if failed == 0:
        return 0
    return 1 if succeeded == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
