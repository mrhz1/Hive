import json
import logging
import os
import tempfile
import time
from typing import Optional

log = logging.getLogger(__name__)

OCR_PERCENT_CEILING = 97.0

MIN_WRITE_INTERVAL = 0.5


class ProgressWriter:

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


    def adopt(self) -> "ProgressWriter":
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
        self._state.update(
            stage="ocr",
            file_index=index,
            source=os.path.basename(source),
            page=0,
            page_total=max(0, page_total),
        )
        self._flush(force=True)

    def page(self, page_number: int) -> None:
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


    def _percent(self) -> float:
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
    if not path:
        return NullProgress()
    return ProgressWriter(path, file_total=file_total)
