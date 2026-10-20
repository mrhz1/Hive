import time

from app import intake, intake_run, intake_worker
from app.ids import DEFAULT_PATIENT_CODE_PATTERN, code_formats, patient_code_pattern

RATE_WINDOW_MINUTES = 15
CACHE_SECONDS = 30

_counts_cache = {}


def files_per_minute(heartbeats, now):
    current_minute = int(now // 60 * 60)
    start = current_minute - RATE_WINDOW_MINUTES * 60
    total = 0
    first_minute = None
    for hb in heartbeats:
        for minute, count in (hb.get("per_minute") or {}).items():
            minute = int(minute)
            if start <= minute < current_minute and count:
                total += count
                if first_minute is None or minute < first_minute:
                    first_minute = minute
    if first_minute is None:
        return 0.0
    return total / max(1, (current_minute - first_minute) // 60)


def problem_counts(now):
    cached = _counts_cache.get("counts")
    if cached and now - cached[0] < CACHE_SECONDS:
        return cached[1]
    counts = {
        "failed": intake.count_files(intake.failed_root()),
        "needs_attention": intake.count_files(intake.attention_root()),
    }
    _counts_cache["counts"] = (now, counts)
    return counts


def clear_cache():
    _counts_cache.clear()


def progress():
    now = time.time()
    heartbeats = intake_worker.read_heartbeats()

    reports = intake.list_reports(1)
    last_finished = float(reports[0].get("finished_at") or 0) if reports else 0.0

    workers = []
    for hb in heartbeats:
        last_seen = float(hb.get("last_seen") or 0)
        alive = intake_worker.is_alive(hb)
        stopped_by_hand = hb.get("status") == intake_run.STOPPED
        clean = hb.get("status") == "idle" or stopped_by_hand
        if alive and not stopped_by_hand:
            status = hb.get("status")
        elif stopped_by_hand or not clean:
            status = "stopped"
        else:
            status = "finished"
        workers.append(
            {
                "name": hb.get("name"),
                "host": hb.get("host"),
                "shards": hb.get("shards") or [],
                "of": hb.get("of") or 1,
                "workers": hb.get("workers") or 1,
                "status": status,
                "crashed_after_last_run": not alive and not clean and last_seen > last_finished,
                "alive": alive and not stopped_by_hand,
                "last_seen": last_seen,
                "seconds_since_seen": max(0.0, now - last_seen),
                "current": hb.get("current") or [],
                "progress": (hb.get("progress") or []) if alive and not stopped_by_hand else [],
                "done": int(hb.get("done") or 0),
                "failed": int(hb.get("failed") or 0),
                "per_hour": round(files_per_minute([hb], now) * 60, 1),
            }
        )
    workers.sort(key=lambda w: (not w["alive"], w["name"] or ""))

    running = intake_run.is_running()
    stalled = False
    for w in workers:
        if w["crashed_after_last_run"] and not running and w["current"]:
            stalled = True
    for w in workers:
        del w["crashed_after_last_run"]

    status = intake.read_json(intake.state_dir() / "status.json")
    remaining = status.get("remaining")
    rate = files_per_minute(heartbeats, now)
    eta = None
    if remaining and rate > 0 and running:
        eta = round(remaining / rate * 60)

    counts = problem_counts(now)
    start = None if running else intake_run.pending_start()
    stop = {} if running else intake_run.stop_record()
    return {
        "running": running,
        "starting": start is not None,
        "start_requested_at": start.get("requested_at") if start else None,
        "remaining": remaining,
        "remaining_counted_at": status.get("counted_at"),
        "done": sum(w["done"] for w in workers),
        "failed": counts["failed"],
        "needs_attention": counts["needs_attention"],
        "per_hour": round(rate * 60, 1),
        "eta_seconds": eta,
        "workers": workers,
        "stalled": stalled,
        "stopped_by": stop.get("by"),
        "stopped_at": stop.get("at"),
        "stalled_reason": "A worker stopped in the middle of a run. Click Start to continue." if stalled else None,
        "as_of": now,
        "code_formats": [
            {"prefix": prefix, "digits": digits} for prefix, digits in code_formats()
        ],
        "code_pattern": patient_code_pattern(),
        "code_pattern_is_default": patient_code_pattern() == DEFAULT_PATIENT_CODE_PATTERN,
    }


FINISHED_LIMIT = 500
_pages_cache = {}


def run_started_at(heartbeats=None):
    heartbeats = intake_worker.read_heartbeats() if heartbeats is None else heartbeats
    starts = [float(hb.get("started_at") or 0) for hb in heartbeats if hb.get("started_at")]
    return min(starts) if starts else None


def page_count(path):
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    key = str(path)
    cached = _pages_cache.get(key)
    if cached and cached[0] == mtime:
        return cached[1]
    pages = None
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            import fitz

            with fitz.open(key) as document:
                pages = document.page_count
        elif suffix in (".dcm", ".dicom"):
            import pydicom

            dataset = pydicom.dcmread(key, stop_before_pixels=True)
            pages = int(getattr(dataset, "NumberOfFrames", 1) or 1)
    except Exception:
        pages = None
    if len(_pages_cache) > 5000:
        _pages_cache.clear()
    _pages_cache[key] = (mtime, pages)
    return pages


def _done_since(since):
    root = intake.deidentified_root()
    found = []
    if not root.is_dir():
        return found
    for sidecar in root.rglob(f"*{intake.SIDECAR_SUFFIX}"):
        if sidecar.name.endswith(intake.REASON_SUFFIX):
            continue
        try:
            if sidecar.stat().st_mtime < since:
                continue
        except OSError:
            continue
        info = intake.read_json(sidecar)
        finished = float(info.get("created_at") or 0)
        if finished < since:
            continue
        document = sidecar.with_name(sidecar.name[: -len(intake.SIDECAR_SUFFIX)])
        found.append(
            {
                "status": "done",
                "path": info.get("relative_path") or document.name,
                "output": document.name,
                "finished_at": finished,
                "document": document,
                "detail": info.get("method"),
            }
        )
    return found


def _problems_since(kind, status, since):
    found = []
    for item in intake.list_problem_files(kind):
        finished = float(item.get("moved_at") or 0)
        if finished < since:
            continue
        found.append(
            {
                "status": status,
                "path": item["path"],
                "output": None,
                "finished_at": finished,
                "document": None,
                "detail": item.get("reason"),
            }
        )
    return found


def finished_files(limit=FINISHED_LIMIT):
    since = run_started_at()
    if since is None:
        return {"since": None, "total": 0, "files": []}
    rows = (
        _done_since(since)
        + _problems_since("failed", "failed", since)
        + _problems_since("attention", "excluded", since)
    )
    rows.sort(key=lambda r: r["finished_at"], reverse=True)
    total = len(rows)
    files = []
    for number, row in zip(range(total, 0, -1), rows[:limit]):
        document = row.pop("document")
        row["number"] = number
        row["pages"] = page_count(document) if document is not None else None
        files.append(row)
    return {"since": since, "total": total, "files": files}
