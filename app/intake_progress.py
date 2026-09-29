import os
import time
from pathlib import Path
from typing import List, Optional

from app import intake, intake_worker
from app.crud import intake_files as crud

CACHE_SECONDS = float(os.environ.get("INTAKE_PROGRESS_CACHE_SECONDS", "10"))
RATE_WINDOW_MINUTES = 15

ACTIVE_STATUSES = ["queued", "processing", "done", "failed", "claimed", "submitted"]
FINISHED_STATUSES = ["done", "failed", "claimed", "submitted"]
PENDING_STATUSES = ["queued", "processing"]

_cache = {}


def clear_cache():
    _cache.clear()


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


def progress(cursor, root: Optional[Path] = None) -> dict:
    root = root or intake.intake_root()
    now = time.time()

    cached = _cache.get("counts")
    if not cached or now - cached[0] >= CACHE_SECONDS:
        cached = (now, crud.status_counts(cursor))
        _cache["counts"] = cached
    counts = cached[1]

    heartbeats = intake_worker.read_heartbeats(root)
    workers = []
    for hb in heartbeats:
        last_seen = float(hb.get("last_seen") or 0)
        alive = now - last_seen <= intake_worker.HEARTBEAT_STALE_SECONDS
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

    total = 0
    finished = 0
    remaining = 0
    for status, n in counts.items():
        if status in ACTIVE_STATUSES:
            total += n
        if status in FINISHED_STATUSES:
            finished += n
        if status in PENDING_STATUSES:
            remaining += n

    rate = files_per_minute(heartbeats, now)
    eta = None
    if remaining and rate > 0:
        eta = round(remaining / rate * 60)

    stalled = remaining > 0 and not any(w["alive"] for w in workers)
    stalled_reason = None
    if stalled:
        last_seen = max([w["last_seen"] for w in workers], default=None)
        if last_seen:
            minutes = int((now - last_seen) // 60)
            stalled_reason = (
                f"{remaining:,} file(s) are waiting and no worker has reported "
                f"for {minutes} minute(s). Restart the watcher or the Job, it "
                f"continues from where it stopped."
            )
        else:
            stalled_reason = (
                f"{remaining:,} file(s) are waiting and no worker has reported "
                f"yet. Start the watcher (make intake-watch) or the Job."
            )

    return {
        "counts": counts,
        "total": total,
        "finished": finished,
        "done": counts.get("done", 0) + counts.get("claimed", 0) + counts.get("submitted", 0),
        "failed": counts.get("failed", 0),
        "remaining": remaining,
        "processing": counts.get("processing", 0),
        "needs_a_person": counts.get("skipped", 0) + counts.get("conflict", 0),
        "percent": round(finished / total * 100, 2) if total else 0.0,
        "per_hour": round(rate * 60, 1),
        "eta_seconds": eta,
        "workers": workers,
        "stalled": stalled,
        "stalled_reason": stalled_reason,
        "as_of": now,
    }


def batches(cursor, limit: int = 20) -> List[dict]:
    now = time.time()
    cached = _cache.get("batches")
    if not cached or now - cached[0] >= CACHE_SECONDS:
        cached = (now, crud.batch_counts(cursor))
        _cache["batches"] = cached
    counts_by_batch = cached[1]

    rows = []
    for batch in crud.list_batches(cursor)[:limit]:
        counts = counts_by_batch.get(batch.id)
        if not counts:
            continue

        total = 0
        finished = 0
        remaining = 0
        for status, n in counts.items():
            if status in ACTIVE_STATUSES:
                total += n
            if status in FINISHED_STATUSES:
                finished += n
            if status in PENDING_STATUSES:
                remaining += n

        rows.append(
            {
                "id": batch.id,
                "root": batch.root,
                "started_at": batch.started_at,
                "counts": counts,
                "total": total,
                "finished": finished,
                "remaining": remaining,
                "failed": counts.get("failed", 0),
                "needs_a_person": counts.get("skipped", 0) + counts.get("conflict", 0),
                "percent": round(finished / total * 100, 2) if total else 100.0,
            }
        )
    return rows
