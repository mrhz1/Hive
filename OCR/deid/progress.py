"""Per-page progress, written where the API can read it.

The Job runs in its own container: the API cannot see its stdout and has
nothing to ask it. What the two *do* share is `FILE_STORAGE_DIR` (see
DEPLOYMENT.md), so progress crosses that boundary as a small JSON file
rewritten as the run advances.

Deliberately not the database. A Hive write costs seconds -- the reason
access logs are batched behind `ACCESS_LOG_MAX_BATCH` -- and a page of
OCR takes 20-30s, so per-page status in Hive would be a measurable tax
on the run it is reporting. A file write is sub-millisecond.

Stdlib only, because this is imported from *both* venvs and they share
no third-party package (see requirements-ocr.txt).

Nothing here raises. Progress is telemetry: a run must not fail because
a status file could not be written.
"""
import json
import logging
import os
import tempfile
import time
from typing import Optional

log = logging.getLogger(__name__)

# Stage 1 was 590s of a 606s run on the 20-page sample, so OCR is very
# nearly the whole wait. Giving redaction the last 3% keeps the bar
# honest: it stops just short until the document is actually written.
OCR_PERCENT_CEILING = 97.0

# A page takes tens of seconds, so per-page writes are already rare. This
# only guards the case that is not paced by OCR -- a DICOM whose frames
# decode in milliseconds -- from rewriting the file hundreds of times a
# second.
MIN_WRITE_INTERVAL = 0.5


class ProgressWriter:
    """Rewrites one JSON file as the run advances."""

    def __init__(self, path: str, file_total: int = 1):
        self.path = path
        self._last_write = 0.0
        self._state = {
            "schema": 1,
            "stage": "starting",
            "file_index": 0,
            "file_total": max(1, file_total),
            "source": "",
            "page": 0,
            "page_total": 0,
            "percent": 0.0,
            "updated_at": 0.0,
        }

    # -- transitions -------------------------------------------------

    def adopt(self) -> "ProgressWriter":
        """Continue from what is already in the file, if anything is.

        The orchestrator writes the terminal state, but it is a different
        process from the stage that wrote every update before it. Without
        this, closing a run out would blank the page counter -- and
        "failed at page 41 of 100" is the useful half of a failure.
        """
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                existing = json.load(fh)
        except (OSError, ValueError):
            return self

        if isinstance(existing, dict):
            for key in ("source", "page", "page_total", "file_index", "file_total"):
                if key in existing:
                    self._state[key] = existing[key]
        return self

    def document(self, index: int, source: str, page_total: int) -> None:
        """Starting a new document, of which we now know the length."""
        self._state.update(
            stage="ocr",
            file_index=index,
            source=os.path.basename(source),
            page=0,
            page_total=max(0, page_total),
        )
        self._flush(force=True)

    def page(self, page_number: int) -> None:
        """One more page has been read."""
        self._state["page"] = page_number
        self._flush()

    def stage(self, name: str) -> None:
        self._state["stage"] = name
        self._flush(force=True)

    def finish(self) -> None:
        self._state.update(stage="done", percent=100.0)
        self._flush(force=True, percent_computed=True)

    def fail(self, error: str) -> None:
        self._state.update(stage="failed", error=str(error)[:200])
        self._flush(force=True)

    # -- writing -----------------------------------------------------

    def _percent(self) -> float:
        """How far through the whole run we are, as a percentage.

        Counted across files as well as pages, so a multi-document run
        does not restart the bar at every file.
        """
        state = self._state
        if state["stage"] in ("redacting", "done"):
            return OCR_PERCENT_CEILING if state["stage"] == "redacting" else 100.0

        page_total = state["page_total"]
        within = (state["page"] / page_total) if page_total else 0.0
        overall = (state["file_index"] + within) / state["file_total"]
        return round(min(overall, 1.0) * OCR_PERCENT_CEILING, 1)

    def _flush(self, force: bool = False, percent_computed: bool = False) -> None:
        now = time.time()
        if not force and (now - self._last_write) < MIN_WRITE_INTERVAL:
            return

        if not percent_computed:
            self._state["percent"] = self._percent()
        self._state["updated_at"] = now

        try:
            self._write(self._state)
        except Exception as exc:  # pragma: no cover - telemetry never fatal
            log.debug("could not write progress to %s: %s", self.path, exc)
            return

        self._last_write = now

    def _write(self, state: dict) -> None:
        """Replace the file atomically.

        The API reads this while we write it. Writing in place would
        eventually hand it a half-written file and a JSONDecodeError, so
        the new content lands under a temp name in the same directory
        and is moved over the old one -- os.replace is atomic within a
        filesystem.
        """
        directory = os.path.dirname(self.path) or "."
        os.makedirs(directory, exist_ok=True)

        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".progress-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(state, fh)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


class NullProgress:
    """What every call site gets when no progress file was asked for."""

    def adopt(self) -> "NullProgress":
        return self

    def document(self, index: int, source: str, page_total: int) -> None:
        pass

    def page(self, page_number: int) -> None:
        pass

    def stage(self, name: str) -> None:
        pass

    def finish(self) -> None:
        pass

    def fail(self, error: str) -> None:
        pass


def writer(path: Optional[str], file_total: int = 1):
    """A ProgressWriter, or a no-op stand-in when progress is off."""
    if not path:
        return NullProgress()
    return ProgressWriter(path, file_total=file_total)
