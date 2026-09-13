import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

from app.logging_setup import get_logger
from app.storage import STORAGE_ROOT, safe_path_segment

log = get_logger(__name__)

PROGRESS_DIR = STORAGE_ROOT / ".progress"

STALE_AFTER_SECONDS = float(os.environ.get("DEID_PROGRESS_STALE_SECONDS", "300"))


def progress_path(file_id: str) -> Path:
    return PROGRESS_DIR / f"{safe_path_segment(file_id)}.json"


def read(file_id: str) -> Optional[dict]:
    path = progress_path(file_id)

    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        log.debug("progress_unreadable", file_id=file_id, error=str(exc))
        return None

    try:
        state = json.loads(raw)
    except ValueError:
        log.debug("progress_unparsable", file_id=file_id)
        return None

    if not isinstance(state, dict):
        return None

    updated_at = float(state.get("updated_at") or 0.0)
    stage = state.get("stage")

    if stage not in ("done", "failed"):
        if updated_at and (time.time() - updated_at) > STALE_AFTER_SECONDS:
            log.info("progress_stale", file_id=file_id, stage=stage)
            return None

    return state


def read_many(file_ids: List[str]) -> Dict[str, dict]:
    found: Dict[str, dict] = {}
    for file_id in file_ids:
        state = read(file_id)
        if state is not None:
            found[file_id] = state
    return found


def clear(file_id: str) -> None:
    try:
        progress_path(file_id).unlink()
    except FileNotFoundError:
        return
    except OSError as exc:
        log.debug("progress_unlink_failed", file_id=file_id, error=str(exc))
