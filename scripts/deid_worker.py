"""Cloudera AI job entrypoint: drain the de-identification queue.

The API can de-identify a file in a background task (DEID_BACKEND=inline),
which is fine at low volume but keeps minutes of CPU inside the web
process and requires the OCR virtualenvs to sit next to the API. This
script is the same work, scheduled instead:

    python scripts/deid_worker.py                # queued, then pending
    python scripts/deid_worker.py --limit 20     # cap one run
    python scripts/deid_worker.py --file-id abc  # exactly one file
    DEID_FILE_ID=abc python scripts/deid_worker.py
    DEID_RETRY_STALE_MINUTES=60 python scripts/deid_worker.py

It calls app.deid.run_deidentification -- the exact function the API
calls inline -- so moving between the two changes scheduling, not
behaviour.

## Two ways a run is started

**Triggered.** The API sets the row to `queued` and starts a Job run with
DEID_FILE_ID set (app/cloudera.py). That run does the one file somebody
is waiting for.

**Scheduled.** A cron'd run with no DEID_FILE_ID drains everything:
`queued` first (someone asked), then `pending` (uploaded, never
processed). That is also what recovers a row whose trigger never made it
to the control plane.

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

from app.crud import patient_files as crud  # noqa: E402
from app.db import hive_cursor  # noqa: E402
from app.deid import run_deidentification  # noqa: E402
from app.logging_setup import configure_logging, get_logger  # noqa: E402

log = get_logger("deid_worker")

# 'queued' before 'pending': a file somebody is actively waiting on
# should not sit behind a backlog of uploads nobody has asked about.
CLAIMABLE = ("queued", "pending")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="De-identify pending patient files")
    parser.add_argument(
        "--file-id",
        default=os.environ.get("DEID_FILE_ID"),
        help=(
            "Process exactly this file and nothing else. Set by the API "
            "when a user triggers a run; falls back to $DEID_FILE_ID, "
            "which is how a Cloudera Job run receives it."
        ),
    )
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
            "Also pick up rows stuck in 'processing' whose file was "
            "uploaded this many minutes ago (0 = never). Guards against a "
            "run that died mid-file. NOTE: patient_files has no "
            "updated_at column, so this measures age since upload, not "
            "since the row was claimed -- set it comfortably longer than "
            "a run takes, or a file uploaded yesterday will be re-claimed "
            "the moment it starts processing."
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
    """Files awaiting de-identification, most-wanted first.

    Filtered in Python rather than SQL because the whole table is small
    and this keeps the query trivial; move it into the WHERE clause if
    the file count ever grows large enough to matter.
    """
    with hive_cursor() as cursor:
        every = crud.list_files(cursor)

    # Sort within each status band by age, then concatenate the bands, so
    # the CLAIMABLE ordering (queued before pending) actually survives.
    queue = []
    for status in CLAIMABLE:
        band = [f for f in every if f.deid_status == status]
        band.sort(key=lambda f: f.created_at)
        queue.extend(band)

    if retry_stale_minutes > 0:
        stuck = [
            f
            for f in every
            if f.deid_status == "processing"
            and _is_stale(f.created_at, retry_stale_minutes)
        ]
        if stuck:
            log.warning("retrying_stale_files", count=len(stuck))
            stuck.sort(key=lambda f: f.created_at)
            queue.extend(stuck)

    return queue[:limit] if limit > 0 else queue


def collect_one(file_id: str):
    """The single file a triggered run was started for.

    Deliberately does not filter on status: the API has already marked it
    `queued`, and refusing to re-run a `done` or `failed` file here would
    make the UI's Re-run button silently do nothing.
    """
    with hive_cursor() as cursor:
        record = crud.get_file(cursor, file_id)

    if record is None:
        log.error("file_not_found", file_id=file_id)
        return []
    return [record]


def main(argv=None) -> int:
    args = parse_args(argv)
    configure_logging()

    if args.file_id:
        queue = collect_one(args.file_id)
        if not queue:
            return 1
    else:
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
