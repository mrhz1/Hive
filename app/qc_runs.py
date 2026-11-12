"""QC runs from the dashboard (protocol 9.1.13).

The check itself is app/qc.py, the same code the scheduled script runs. Each
run writes a folder under REPORTS_DIR (qc-<timestamp>) with issues.csv,
suppressed.csv, the workbook, one PDF for everything, one PDF per cohort and
summary.json. This module lists those folders, pages through their issues,
starts a run in the background and edits the suppressions file.
"""

import csv
import json
import re
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import List, Optional

from app import qc, reports
from app.db import hive_cursor
from app.errors import ConflictError, NotFoundError, ValidationError
from app.logging_setup import get_logger

log = get_logger(__name__)

_NAME = re.compile(r"^qc-\d{8}T\d{6}Z$")
_COHORT = re.compile(r"^[A-Z]{1,10}$")
PAGE_SIZE_MAX = 200
SUPPRESSION_COLUMNS = ["rule", "record", "reason", "by", "date"]

_lock = threading.Lock()
_state = {"running": False, "started_at": None, "run_by": None, "error": None}
_suppressions_lock = threading.Lock()


def state() -> dict:
    return dict(_state)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _work(run_by: str) -> None:
    try:
        with hive_cursor() as cursor:
            qc.run(cursor, run_by=run_by)
        _state["error"] = None
    except Exception as exc:  # shown on the page; the run is not retried
        log.error("qc_run_failed", error=str(exc))
        _state["error"] = str(exc)
    finally:
        _state["running"] = False
        _lock.release()


def start(run_by: str) -> dict:
    if not _lock.acquire(blocking=False):
        raise ConflictError("A QC run is already going; wait for it to finish")
    _state.update(running=True, started_at=_now(), run_by=run_by, error=None)
    threading.Thread(target=_work, args=(run_by,), daemon=True, name="qc-run").start()
    log.info("qc_run_started", run_by=run_by)
    return state()


def _summary(folder: Path) -> dict:
    data = {}
    path = folder / qc.SUMMARY_FILE
    if path.is_file():
        try:
            data = json.loads(path.read_text())
        except ValueError:
            data = {}
    stamp = folder.name[3:]
    made = data.get("made_at") or (
        datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat()
    )
    return {
        "name": folder.name,
        "made_at": made,
        "run_by": data.get("run_by") or "",
        "issues": data.get("issues"),
        "high": data.get("high"),
        "suppressed": data.get("suppressed"),
        "stale_suppressions": data.get("stale_suppressions") or 0,
        "rules": data.get("rules") or {},
        "cohorts": data.get("cohorts") or {},
    }


def list_runs(limit: int = 20) -> List[dict]:
    root = reports.reports_root()
    if not root.is_dir():
        return []
    folders = sorted(
        (p for p in root.iterdir() if p.is_dir() and _NAME.match(p.name)),
        key=lambda p: p.name,
        reverse=True,
    )
    return [_summary(p) for p in folders[:limit]]


def folder(name: str) -> Path:
    if not _NAME.match(name or ""):
        raise ValidationError("Not a QC run")
    path = reports.reports_root() / name
    if not path.is_dir():
        raise NotFoundError("This QC run is not on disk any more")
    return path


def get_run(name: str) -> dict:
    return _summary(folder(name))


def issues(name: str, page: int = 1, size: int = 50, query: str = "",
           rule: str = "", cohort: str = "", suppressed: bool = False) -> dict:
    path = folder(name) / ("suppressed.csv" if suppressed else "issues.csv")
    page, size = max(1, page), max(1, min(size, PAGE_SIZE_MAX))
    needle, rule, cohort = (query or "").strip().lower(), (rule or "").upper(), (cohort or "").upper()
    start = (page - 1) * size
    rows, total, columns = [], 0, []
    if path.is_file():
        from app.blobstore import open_file

        with open_file(path, "r", newline="", encoding="utf-8") as handle:
            reader = csv.reader(handle)
            columns = next(reader, [])
            for row in reader:
                if rule and (row[0] if row else "") != rule:
                    continue
                if cohort and qc.cohort_of(row[4] if len(row) > 4 else "") != cohort:
                    continue
                if needle and not any(needle in cell.lower() for cell in row):
                    continue
                if start <= total < start + size:
                    rows.append(row)
                total += 1
    return {"columns": columns, "rows": rows, "total": total, "page": page, "size": size}


def report_file(name: str, kind: str, cohort: Optional[str] = None) -> Path:
    base = folder(name)
    if kind == "xlsx":
        path = base / "qc-report.xlsx"
    elif kind == "pdf" and cohort:
        if not _COHORT.match(cohort.upper()):
            raise ValidationError("Not a cohort")
        path = base / f"qc-report-{cohort.upper()}.pdf"
    elif kind == "pdf":
        path = base / "qc-report.pdf"
    else:
        raise ValidationError("Pick pdf or xlsx")
    if not path.is_file():
        raise NotFoundError("This report is not in the run")
    return path


def suppressions() -> List[dict]:
    rows = []
    for (rule_code, record), line in qc.load_suppressions().items():
        rows.append({
            "rule": rule_code,
            "record": record,
            "reason": line.get("reason", ""),
            "by": line.get("by", ""),
            "date": line.get("date", ""),
        })
    return sorted(rows, key=lambda r: (r["rule"], r["record"]))


def _write(rows: List[dict]) -> None:
    from app.blobstore import open_file

    path = qc.suppressions_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    # the store writes whole files atomically, so no temporary file is needed
    with open_file(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUPPRESSION_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in SUPPRESSION_COLUMNS})


def suppress(rule_code: str, record: str, reason: str, by: str) -> dict:
    rule_code, record, reason = (rule_code or "").strip().upper(), (record or "").strip(), (reason or "").strip()
    if rule_code not in qc.RULES:
        raise ValidationError(f"Unknown QC rule '{rule_code}'")
    if not record:
        raise ValidationError("Say which record to suppress")
    if not reason:
        raise ValidationError("Say why this issue is accepted")
    entry = {"rule": rule_code, "record": record, "reason": reason, "by": by,
             "date": date.today().isoformat()}
    with _suppressions_lock:
        rows = [r for r in suppressions() if (r["rule"], r["record"]) != (rule_code, record)]
        _write(rows + [entry])
    log.info("qc_suppressed", rule=rule_code, record=record, by=by)
    return entry


def unsuppress(rule_code: str, record: str) -> dict:
    key = ((rule_code or "").strip().upper(), (record or "").strip())
    with _suppressions_lock:
        rows = suppressions()
        found = [r for r in rows if (r["rule"], r["record"]) == key]
        if not found:
            raise NotFoundError("This issue is not suppressed")
        _write([r for r in rows if (r["rule"], r["record"]) != key])
    log.info("qc_unsuppressed", rule=key[0], record=key[1])
    return found[0]


def rules() -> List[dict]:
    return [{"code": r.code, "severity": r.severity, "text": r.text} for r in qc.RULES.values()]
