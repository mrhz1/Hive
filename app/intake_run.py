import fcntl
import os
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from app import intake, intake_notices, intake_worker
from app.logging_setup import get_logger

log = get_logger(__name__)

LOCK_FILE = "run.lock"
START_REQUEST_FILE = "start_requested.json"
STOP_RECORD_FILE = "stopped.json"
CML_RUN_FILE = "cml_run.json"
RUN_SCRIPT = "intake_run"
STOPPED = "stopped"
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


def clear_stop_record():
    (intake.state_dir() / STOP_RECORD_FILE).unlink(missing_ok=True)


def stop_record():
    return intake.read_json(intake.state_dir() / STOP_RECORD_FILE)


def pending_start():
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
    clear_stop_record()

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
    intake_notices.notify_run_finished(report)
    return report


def start_in_background():
    if os.environ.get("DEID_BACKEND", "inline").strip().lower() == "cml_job":
        from app.cloudera import start_intake_job_run

        run_id = start_intake_job_run()
        intake.write_json(intake.state_dir() / CML_RUN_FILE, {"run_id": run_id})
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


def _children_by_parent():
    children = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
        except OSError:
            continue
        parent = int(stat.rsplit(")", 1)[1].split()[1])
        children.setdefault(parent, []).append(int(entry.name))
    return children


def process_tree(roots):
    children = _children_by_parent()
    found, todo = [], list(roots)
    while todo:
        pid = todo.pop()
        if pid in found:
            continue
        found.append(pid)
        todo.extend(children.get(pid, []))
    return found


def is_run_process(pid):
    try:
        command = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return False
    return RUN_SCRIPT.encode() in command


def _send(pids, sig):
    for pid in pids:
        try:
            os.kill(pid, sig)
        except (ProcessLookupError, PermissionError):
            pass


def kill_tree(roots):
    frozen = []
    for _ in range(5):
        fresh = [pid for pid in process_tree(roots) if pid not in frozen]
        if not fresh:
            break
        _send(fresh, signal.SIGSTOP)
        frozen.extend(fresh)
    _send(frozen, signal.SIGKILL)
    return frozen


def local_runs():
    host = socket.gethostname()
    found = []
    for hb in intake_worker.read_heartbeats():
        pid = int(hb.get("pid") or 0)
        if hb.get("host") == host and pid and is_run_process(pid):
            found.append(pid)
    return found


def _mark_stopped(by, pids=None):
    clear_start_request()
    intake.write_json(
        intake.state_dir() / STOP_RECORD_FILE, {"by": by, "at": time.time()}
    )
    folder = intake.state_dir() / "workers"
    for path in folder.glob("*.json") if folder.is_dir() else []:
        data = intake.read_json(path)
        if not data or data.get("status") != "working":
            continue
        if pids is not None and int(data.get("pid") or 0) not in pids:
            continue
        data.update(status=STOPPED, current=[], progress=[], last_seen=time.time())
        intake.write_json(path, data)


def stop(by=None):
    if os.environ.get("DEID_BACKEND", "inline").strip().lower() == "cml_job":
        from app.cloudera import stop_intake_job_run

        run_id = intake.read_json(intake.state_dir() / CML_RUN_FILE).get("run_id")
        if not run_id:
            return {"stopped": False, "processes": 0}
        stop_intake_job_run(run_id)
        (intake.state_dir() / CML_RUN_FILE).unlink(missing_ok=True)
        _mark_stopped(by)
        log.info("intake_job_stopped", run_id=run_id, by=by)
        return {"stopped": True, "run_id": run_id, "processes": 0}

    roots = local_runs()
    if not roots:
        return {"stopped": False, "processes": 0}
    killed = kill_tree(roots)
    _mark_stopped(by, set(roots))
    log.info("intake_stopped", by=by, processes=len(killed))
    return {"stopped": True, "processes": len(killed)}
