"""Reading the progress the de-identification Job writes.

The Job runs in its own container, so the API cannot ask it anything.
The one thing they share is `FILE_STORAGE_DIR` (DEPLOYMENT.md), and the
Job rewrites a small JSON file there as it works -- see
OCR/deid/progress.py for the writing half and for why this is a file
rather than a Hive column.

Everything here is best-effort. Progress is decoration on top of
`deid_status`, which remains the truth about whether a file is done.
"""
import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

from app.logging_setup import get_logger
from app.storage import STORAGE_ROOT, safe_path_segment

log = get_logger(__name__)

PROGRESS_DIR = STORAGE_ROOT / ".progress"

# Older than this and the writer is gone without having said so -- the
# Job was killed, the container went away. Rather than show a bar frozen
# at 41% forever, the record is treated as absent and the caller falls
# back to `deid_status`. Comfortably longer than a page takes (20-30s)
# so a slow page is never mistaken for a dead job.
STALE_AFTER_SECONDS = float(os.environ.get("DEID_PROGRESS_STALE_SECONDS", "300"))


def progress_path(file_id: str) -> Path:
    """Where the Job should write progress for this file."""
    return PROGRESS_DIR / f"{safe_path_segment(file_id)}.json"


def read(file_id: str) -> Optional[dict]:
    """This file's progress, or None if there is nothing usable."""
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
        # A torn read should be impossible -- the writer swaps the file in
        # with os.replace -- so this means the content is genuinely bad.
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
    """Progress for several files, skipping those that have none.

    One directory's worth of small reads: this is what the file list
    polls, and doing it per file would be one request each.
    """
    found: Dict[str, dict] = {}
    for file_id in file_ids:
        state = read(file_id)
        if state is not None:
            found[file_id] = state
    return found


def clear(file_id: str) -> None:
    """Drop the progress record for a file that is no longer running."""
    try:
        progress_path(file_id).unlink()
    except FileNotFoundError:
        return
    except OSError as exc:
        log.debug("progress_unlink_failed", file_id=file_id, error=str(exc))
