"""Cloudera AI job entrypoint: drain the de-identification queue."""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

def _repo_root():
    """Locate the repo root without assuming how we were started."""
    candidates = []
    here = globals().get("__file__")
    if here:
        own_dir = Path(here).resolve().parent
        candidates.append(("__file__ dir", own_dir))
        candidates.append(("__file__ parent", own_dir.parent))
    for var in ("HIVE_REPO_ROOT", "CDSW_PROJECT_DIR", "CDSW_PROJECT"):
        value = os.environ.get(var)
        if value:
            candidates.append(("$" + var, Path(value)))
    cwd = Path.cwd().resolve()
    candidates.append(("cwd", cwd))
    candidates.append(("cwd parent", cwd.parent))

    for source, candidate in candidates:
        if (candidate / "app" / "deid.py").is_file():
            return candidate

    tried = "\n".join(
        "  {:<12} {}  ({})".format(
            source,
            candidate,
            "exists" if candidate.is_dir() else "no such directory",
        )
        for source, candidate in candidates
    )
    listing = "  ".join(sorted(p.name for p in cwd.iterdir())[:20]) or "(empty)"
    raise RuntimeError(
        "Cannot locate the Hive repo root -- no app/deid.py under any of:\n"
        + tried
        + "\nContents of {}:\n  {}".format(cwd, listing)
        + "\nSet HIVE_REPO_ROOT (Job -> Environment Variables) to the "
        "directory that contains app/. It must be a real environment "
        "variable: .env.local is loaded by app.db, which cannot be "
        "imported until this has already succeeded."
    )


REPO_ROOT = _repo_root()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.crud import patient_application_files as crud  # noqa: E402
from app.db import hive_cursor  # noqa: E402
from app.deid import run_deidentification  # noqa: E402
from app.logging_setup import configure_logging, get_logger  # noqa: E402

log = get_logger("deid_worker")

CLAIMABLE = ("queued", "pending")


def _under_ipython_kernel() -> bool:
    """Whether sys.argv belongs to a Jupyter kernel rather than to us."""
    prog = Path(sys.argv[0]).name if sys.argv else ""
    if prog.startswith("ipykernel_launcher"):
        return True
    if "ipykernel" in sys.modules:
        return True
    return any(
        arg.endswith(".json") and "jupyter" in arg and "kernel-" in arg
        for arg in sys.argv[1:]
    )


def _cli_argv():
    """Args for argparse: the real ones, or none at all under a kernel."""
    if _under_ipython_kernel():
        return []
    return sys.argv[1:]


def parse_args(argv=None):
    if argv is None:
        argv = _cli_argv()
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
            "run that died mid-file. NOTE: patient_application_files "
            "has no "
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
    """Files awaiting de-identification, most-wanted first."""
    with hive_cursor() as cursor:
        every = crud.list_files(cursor)

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
    """The single file a triggered run was started for."""
    with hive_cursor() as cursor:
        record = crud.get_file(cursor, file_id)

    if record is None:
        log.error("file_not_found", file_id=file_id)
        return []
    return [record]


def process(record) -> bool:
    run_deidentification(record.id)

    # run_deidentification never raises; re-read to see what it did.
    with hive_cursor() as cursor:
        after = crud.get_file(cursor, record.id)

    return bool(after and after.deid_status == "done")


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

    log.info("draining_queue", count=len(queue), triggered=bool(args.file_id))

    succeeded = 0
    failed = 0

    for record in queue:
        if process(record):
            succeeded += 1
        else:
            failed += 1

    log.info("queue_drained", succeeded=succeeded, failed=failed)

    if failed == 0:
        return 0
    return 1 if succeeded == 0 else 2


if __name__ == "__main__":
    _rc = main()
    if _under_ipython_kernel():
        if _rc:
            raise SystemExit(_rc)
    else:
        sys.exit(_rc)
