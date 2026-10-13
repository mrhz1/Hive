"""Locking the whole app during a security incident (protocol section 4).

While locked, every request is refused with 503 "locked", except for users
with `security:manage` (to investigate and unlock) and the two calls the
page needs to say so (/me, /security/lockdown). The state is a file on
shared storage (SECURITY_STATE_DIR), so every API instance and the alert job
see it; it is re-read every few seconds.

Locking and unlocking are emailed to ALERT_EMAIL_TO (the Program Manager,
the application specialist and Host IT) and written to the audit log.
"""

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel

from app.errors import AppError, ValidationError
from app.logging_setup import get_logger
from app.mailer import send_email
from app.storage import _configured_dir

log = get_logger(__name__)

MANAGE = "security:manage"
EXEMPT_PATHS = ("/me", "/security/lockdown")
CACHE_SECONDS = 5
LEVELS = ("low", "high", "critical")

_lock = threading.Lock()
_cache: dict = {"at": 0.0, "state": None, "path": None}


class LockedError(AppError):
    status_code = 503
    code = "locked"


class LockdownState(BaseModel):
    locked: bool
    reason: Optional[str] = None
    level: Optional[str] = None
    locked_at: Optional[str] = None
    locked_by: Optional[str] = None


def _state_file() -> Path:
    return _configured_dir("SECURITY_STATE_DIR", "storage/security") / "lockdown.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read() -> Optional[dict]:
    try:
        return json.loads(_state_file().read_text())
    except (OSError, ValueError):
        return None


def state(fresh: bool = False) -> LockdownState:
    path = _state_file()
    with _lock:
        if fresh or _cache["path"] != path or time.monotonic() - _cache["at"] > CACHE_SECONDS:
            _cache.update(at=time.monotonic(), state=_read(), path=path)
        data = _cache["state"]
    return LockdownState(locked=True, **data) if data else LockdownState(locked=False)


def contacts(level: str = "high") -> List[str]:
    """Who hears about it: low -> ALERT_EMAIL_LOW_TO (falls back to
    ALERT_EMAIL_TO), anything else -> ALERT_EMAIL_TO."""
    names = ["ALERT_EMAIL_LOW_TO", "ALERT_EMAIL_TO"] if level == "low" else ["ALERT_EMAIL_TO"]
    for name in names:
        raw = os.environ.get(name) or ""
        found = [a.strip() for a in raw.split(",") if a.strip()]
        if found:
            return found
    return []


def lock(reason: str, level: str, by: str) -> LockdownState:
    text = (reason or "").strip()
    if not text:
        raise ValidationError("A reason is required to lock the app")
    if level not in LEVELS:
        raise ValidationError(f"Level must be one of {', '.join(LEVELS)}")
    if state(fresh=True).locked:
        raise ValidationError("The app is already locked")

    data = {"reason": text, "level": level, "locked_at": _now(), "locked_by": by}
    path = _state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data))
    temporary.replace(path)
    log.warning("app_locked", level=level, by=by)

    send_email(
        contacts(level),
        f"Hive LOCKED ({level}): {text[:80]}",
        "\n".join([
            "The Hive app has been locked; nobody without security:manage can use it.",
            "",
            f"Level: {level}",
            f"Reason: {text}",
            f"By: {by}",
            f"At: {data['locked_at']}",
            "",
            "Record the incident on the Security page. The preliminary report is",
            "due within 24 hours and the full report within 72 hours.",
            "",
            "-- Hive",
        ]),
    )
    return state(fresh=True)


def unlock(reason: str, by: str) -> LockdownState:
    text = (reason or "").strip()
    if not text:
        raise ValidationError("A reason is required to unlock the app")
    before = state(fresh=True)
    if not before.locked:
        raise ValidationError("The app is not locked")
    _state_file().unlink(missing_ok=True)
    log.warning("app_unlocked", by=by)
    send_email(
        contacts(before.level or "high"),
        "Hive unlocked",
        "\n".join([
            "The Hive app has been unlocked.",
            "",
            f"Reason: {text}",
            f"By: {by}",
            f"Locked since {before.locked_at} ({before.reason})",
            "",
            "-- Hive",
        ]),
    )
    return state(fresh=True)


def refuse_if_locked(permissions: List[str], path: str) -> None:
    if path in EXEMPT_PATHS or MANAGE in permissions:
        return
    current = state()
    if current.locked:
        raise LockedError(
            "Hive is locked because of a security incident. Try again later "
            "or contact the application specialist."
        )
