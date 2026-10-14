"""Standard data cleanup rules applied when a project's workspace is built
(spec 9.2.1, 9.2.3).

Rules are Python files in CLEANING_DIR (default: cleaning/ in the repo), so
every correction is code that is reviewed and versioned, never an edit in
Excel:

    cleaning/instrument/<table>.py      every row of that table
                                         (patients, applications, documents)
    cleaning/instrument/<MODALITY>.py   documents rows of that modality (ECHO, MR, ...)
    cleaning/cohort/<PREFIX>.py         rows of the patients whose code starts
                                         with PREFIX, in every table

Each file defines

    def clean(table: str, rows: list[dict]) -> list[dict]

and returns the rows to keep (changed in place or new dicts). A file whose
name starts with "_" is skipped. Instrument rules run first, then cohort
rules. What ran and how many rows each changed goes to cleaning_log.csv in
the workspace. A rule that fails stops the build, with its name.
"""

import copy
import importlib.util
import os
from pathlib import Path
from typing import Callable, Dict, List, Tuple

from app.errors import ValidationError
from app.logging_setup import get_logger
from app.storage import REPO_ROOT

log = get_logger(__name__)

TABLES = ("patients", "applications", "documents")
LOG_COLUMNS = ["rule", "table", "rows_in", "rows_out", "rows_changed"]

Rule = Callable[[str, List[dict]], List[dict]]


def cleaning_dir() -> Path:
    value = Path(os.environ.get("CLEANING_DIR", "cleaning"))
    return value if value.is_absolute() else REPO_ROOT / value


def _load(path: Path) -> Rule:
    spec = importlib.util.spec_from_file_location(f"cleaning_rule_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        raise ValidationError(f"Cleaning rule {path.name} could not be loaded: {e}")
    rule = getattr(module, "clean", None)
    if not callable(rule):
        raise ValidationError(f"Cleaning rule {path.name} has no clean(table, rows)")
    return rule


def _rules(kind: str) -> List[Tuple[str, Path]]:
    folder = cleaning_dir() / kind
    if not folder.is_dir():
        return []
    return [
        (path.stem, path)
        for path in sorted(folder.glob("*.py"))
        if not path.name.startswith("_")
    ]


def _run(name: str, rule: Rule, table: str, rows: List[dict], log_rows: List[dict]) -> List[dict]:
    before = copy.deepcopy(rows)
    try:
        after = rule(table, rows)
    except Exception as e:
        raise ValidationError(f"Cleaning rule {name} failed on {table}: {e}")
    if not isinstance(after, list):
        raise ValidationError(f"Cleaning rule {name} did not return a list of rows")
    changed = sum(1 for old, new in zip(before, after) if old != new) + abs(len(after) - len(before))
    log_rows.append(
        {"rule": name, "table": table, "rows_in": len(before),
         "rows_out": len(after), "rows_changed": changed}
    )
    return after


def apply(tables: Dict[str, List[dict]]) -> Tuple[Dict[str, List[dict]], List[dict]]:
    """Run every rule over the tables; returns the cleaned tables and the log."""
    out = {name: list(rows) for name, rows in tables.items()}
    log_rows: List[dict] = []

    for stem, path in _rules("instrument"):
        rule = _load(path)
        name = f"instrument/{path.name}"
        if stem in out:
            out[stem] = _run(name, rule, stem, out[stem], log_rows)
            continue
        modality = stem.upper()
        documents = out.get("documents", [])
        picked = [r for r in documents if (r.get("modality") or "").upper() == modality]
        if picked:
            kept = _run(name, rule, "documents", picked, log_rows)
            others = [r for r in documents if (r.get("modality") or "").upper() != modality]
            out["documents"] = others + kept

    for stem, path in _rules("cohort"):
        rule = _load(path)
        prefix = stem.upper()
        for table in TABLES:
            rows = out.get(table, [])
            picked = [r for r in rows if str(r.get("patient_id") or "").startswith(prefix)]
            if not picked:
                continue
            kept = _run(f"cohort/{path.name}", rule, table, picked, log_rows)
            out[table] = [r for r in rows if not str(r.get("patient_id") or "").startswith(prefix)] + kept

    if log_rows:
        log.info("cleaning_applied", rules=len({r["rule"] for r in log_rows}))
    return out, log_rows
