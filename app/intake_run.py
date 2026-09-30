import fcntl
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from app import intake, intake_worker
from app.logging_setup import get_logger

log = get_logger(__name__)

LOCK_FILE = "run.lock"
START_REQUEST_FILE = "start_requested.json"
START_TIMEOUT_SECONDS = float(os.environ.get("INTAKE_START_TIMEOUT_SECONDS", "900"))
REPO_ROOT = Path(__file__).resolve().parent.parent


def lock_name(shards=None, of=1):
    if shards is None or of <= 1:
        return LOCK_FILE
    return f"run-{of}-" + "_".join(str(s) for s in sorted(shards)) + ".lock"


def acquire_lock(name=LOCK_FILE):
    state_dir = intake.state_dir()
    state_dir.mkdir(parents=True, exist_ok=True)
    f = open(state_dir / name, "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.close()
        return None
    f.write(str(os.getpid()))
    f.flush()
    return f


def release_lock(f):
    fcntl.flock(f, fcntl.LOCK_UN)
    f.close()


def is_running():
    lock = acquire_lock()
    if lock is None:
        return True
    release_lock(lock)
    for hb in intake_worker.read_heartbeats():
        if hb.get("status") == "working" and intake_worker.is_alive(hb):
            return True
    return False


def request_start(**details):
    intake.write_json(
        intake.state_dir() / START_REQUEST_FILE, dict(details, requested_at=time.time())
    )


def clear_start_request():
    (intake.state_dir() / START_REQUEST_FILE).unlink(missing_ok=True)


def pending_start():
    """The start someone asked for that no run has picked up yet, if any.

    Between clicking Start and a worker taking the lock there is nothing
    running to show -- a Cloudera job can take a minute or two to boot.
    """
    request = intake.read_json(intake.state_dir() / START_REQUEST_FILE)
    requested_at = request.get("requested_at") if request else None
    if not requested_at or time.time() - requested_at > START_TIMEOUT_SECONDS:
        return None
    return request


def run(limit=None, pool_size=None, shards=None, of=1, root=None):
    root = root or intake.intake_root()
    lock = acquire_lock(lock_name(shards, of))
    if lock is None:
        return {"outcome": "busy", "detail": "another run is still working"}
    clear_start_request()

    started = time.time()
    try:
        cleaned = intake_worker.clean_up(shards, of)
        totals = intake_worker.process(limit=limit, pool_size=pool_size, shards=shards, of=of, root=root)
    finally:
        release_lock(lock)

    report = dict(
        totals,
        outcome="ran",
        host=socket.gethostname(),
        shards=sorted(intake_worker.my_shards(shards, of)),
        of=of,
        cleaned_up=cleaned,
        started_at=started,
        finished_at=time.time(),
    )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    intake.write_json(intake.state_dir() / "reports" / f"{stamp}-{socket.gethostname()}.json", report)
    log.info("intake_run_finished", **{k: v for k, v in report.items() if k != "shards"})
    return report


def start_in_background():
    if os.environ.get("DEID_BACKEND", "inline").strip().lower() == "cml_job":
        from app.cloudera import start_intake_job_run

        run_id = start_intake_job_run()
        log.info("intake_job_started", run_id=run_id)
        return {"started": True, "run_id": run_id}

    log_file = intake.state_dir() / "last_run.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with open(log_file, "w") as out:
        process = subprocess.Popen(
            [sys.executable, str(REPO_ROOT / "scripts" / "intake_run.py")],
            cwd=str(REPO_ROOT),
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    log.info("intake_process_started", pid=process.pid)
    return {"started": True, "pid": process.pid}
