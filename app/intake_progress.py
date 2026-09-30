import time

from app import intake, intake_run, intake_worker

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

    workers = []
    for hb in heartbeats:
        last_seen = float(hb.get("last_seen") or 0)
        alive = intake_worker.is_alive(hb)
        workers.append(
            {
                "name": hb.get("name"),
                "host": hb.get("host"),
                "shards": hb.get("shards") or [],
                "of": hb.get("of") or 1,
                "workers": hb.get("workers") or 1,
                "status": hb.get("status") if alive else "stopped",
                "alive": alive,
                "last_seen": last_seen,
                "seconds_since_seen": max(0.0, now - last_seen),
                "current": hb.get("current") or [],
                "done": int(hb.get("done") or 0),
                "failed": int(hb.get("failed") or 0),
                "per_hour": round(files_per_minute([hb], now) * 60, 1),
            }
        )
    workers.sort(key=lambda w: (not w["alive"], w["name"] or ""))

    running = intake_run.is_running()
    stalled = False
    for w in workers:
        if w["status"] == "stopped" and not running and w["current"]:
            stalled = True

    status = intake.read_json(intake.state_dir() / "status.json")
    remaining = status.get("remaining")
    rate = files_per_minute(heartbeats, now)
    eta = None
    if remaining and rate > 0 and running:
        eta = round(remaining / rate * 60)

    counts = problem_counts(now)
    start = None if running else intake_run.pending_start()
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
        "stalled_reason": "A worker stopped in the middle of a run. Click Start to continue." if stalled else None,
        "as_of": now,
    }
