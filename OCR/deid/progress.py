import json
import logging
import os
import tempfile
import time

log = logging.getLogger(__name__)

MAX_OCR_PERCENT = 97.0
MIN_WRITE_INTERVAL = 0.5


class ProgressWriter:
    def __init__(self, path, file_total=1):
        self.path = path
        self._last_write = 0.0
        self.state = {
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

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                old = json.load(f)
        except (OSError, ValueError):
            return self

        if isinstance(old, dict):
            for key in ["source", "page", "page_total", "file_index", "file_total"]:
                if key in old:
                    self.state[key] = old[key]
        return self

    def document(self, index, source, page_total):
        self.state["stage"] = "ocr"
        self.state["file_index"] = index
        self.state["source"] = os.path.basename(source)
        self.state["page"] = 0
        self.state["page_total"] = max(0, page_total)
        self.save(force=True)

    def page(self, page_number):
        self.state["page"] = page_number
        self.save()

    def stage(self, name):
        self.state["stage"] = name
        self.save(force=True)

    def finish(self):
        self.state["stage"] = "done"
        self.save(force=True)

    def fail(self, error):
        self.state["stage"] = "failed"
        self.state["error"] = str(error)[:200]
        self.save(force=True)

    def save(self, force=False):
        now = time.time()
        if not force and now - self._last_write < MIN_WRITE_INTERVAL:
            return

        s = self.state
        if s["stage"] == "done":
            s["percent"] = 100.0
        elif s["stage"] == "redacting":
            s["percent"] = MAX_OCR_PERCENT
        else:
            page_part = s["page"] / s["page_total"] if s["page_total"] else 0.0
            done = (s["file_index"] + page_part) / s["file_total"]
            s["percent"] = round(min(done, 1.0) * MAX_OCR_PERCENT, 1)
        s["updated_at"] = now

        folder = os.path.dirname(self.path) or "."
        tmp = None
        try:
            os.makedirs(folder, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=folder, prefix=".progress-", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(s, f)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        except Exception as e:
            if tmp and os.path.exists(tmp):
                os.unlink(tmp)
            log.debug("could not write progress to %s: %s", self.path, e)
            return

        self._last_write = now


class NullProgress:
    def load(self):
        return self

    def document(self, index, source, page_total):
        pass

    def page(self, page_number):
        pass

    def stage(self, name):
        pass

    def finish(self):
        pass

    def fail(self, error):
        pass


def writer(path, file_total=1):
    if not path:
        return NullProgress()
    return ProgressWriter(path, file_total=file_total)
