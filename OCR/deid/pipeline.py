"""Orchestration across two virtualenvs."""
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from deid import model_store
from deid.config import load_config
from deid.results import DocumentResult
from deid.documents import needs_ocr, output_extension
from deid.spans import write_manifest

log = logging.getLogger(__name__)

OCR_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_OCR_PYTHON = str(OCR_ROOT / ".venv-ocr" / "bin" / "python")
DEFAULT_NLP_PYTHON = str(OCR_ROOT / ".venv-nlp" / "bin" / "python")


def ocr_python() -> str:
    return os.environ.get("DEID_OCR_PYTHON", DEFAULT_OCR_PYTHON)


def nlp_python() -> str:
    return os.environ.get("DEID_NLP_PYTHON", DEFAULT_NLP_PYTHON)


def _log_stage_output() -> bool:
    return os.environ.get("DEID_LOG_STAGE_OUTPUT", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


class StageError(RuntimeError):
    """A whole stage failed, as opposed to individual files failing."""


def _failure_detail(stderr: str, stdout: str) -> str:
    """The most useful ~800 characters of a failed stage's output."""
    text = (stderr or stdout or "").strip()
    errors = [
        line
        for line in text.splitlines()
        if "ERROR" in line or "Traceback" in line or "Error:" in line
    ]
    detail = " | ".join(errors) if errors else text
    return detail.strip()[-800:]


def _run_stage(
    interpreter: str,
    script: str,
    manifest_path: str,
    result_path: str,
    stage: str,
) -> List[dict]:
    """Run one stage subprocess and read back its result file."""
    command = [
        interpreter,
        str(OCR_ROOT / "scripts" / script),
        "--manifest",
        manifest_path,
        "--result",
        result_path,
    ]
    log.info("stage %s: %s", stage, " ".join(command))

    try:
        completed = subprocess.run(
            command,
            cwd=str(OCR_ROOT),
            capture_output=True,
            text=True,
            check=False,
            env=os.environ.copy(),
        )
    except FileNotFoundError as exc:
        raise StageError(
            f"{stage} stage interpreter not found at '{interpreter}'. "
            f"Set DEID_{stage.upper()}_PYTHON to the venv that has the "
            f"{stage} dependencies installed."
        ) from exc

    if completed.stderr and (completed.returncode != 0 or _log_stage_output()):
        for line in completed.stderr.strip().splitlines():
            log.info("[%s] %s", stage, line)

    if not os.path.exists(result_path):
        detail = _failure_detail(completed.stderr, completed.stdout)
        raise StageError(
            f"{stage} stage produced no result file "
            f"(exit {completed.returncode}): {detail}"
        )

    with open(result_path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _fail_all(sources: List[str], stage: str, error: str) -> List[DocumentResult]:
    return [
        DocumentResult(
            source_path=source, status="error", error=error, failed_stage=stage
        )
        for source in sources
    ]


def run_pipeline(
    sources: List[str],
    output_dir: str,
    suffix: str = "_deid",
    work_dir: Optional[str] = None,
) -> List[DocumentResult]:
    """De-identify every PDF in `sources`, writing results to `output_dir`."""
    if not sources:
        return []

    output_root = Path(output_dir).expanduser()
    output_root.mkdir(parents=True, exist_ok=True)

    keep_work_dir = os.environ.get("DEID_KEEP_WORK_DIR", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    if work_dir:
        work = Path(work_dir).expanduser()
        work.mkdir(parents=True, mode=0o700, exist_ok=True)
        owned = False
    else:
        work = Path(tempfile.mkdtemp(prefix="deid-work-"))
        owned = True

    try:
        return _run(sources, output_root, suffix, work)
    finally:
        if owned and not keep_work_dir:
            shutil.rmtree(work, ignore_errors=True)
        elif keep_work_dir:
            log.warning(
                "DEID_KEEP_WORK_DIR is set: OCR text (PHI) left in %s", work
            )


def _run_nlp(jobs: List[Dict[str, Any]], work: Path) -> List[DocumentResult]:
    """Stage 2 over a batch of jobs, or nothing if there are none."""
    if not jobs:
        return []

    nlp_manifest = str(work / "nlp-manifest.json")
    write_manifest(nlp_manifest, jobs)

    try:
        nlp_results = _run_stage(
            nlp_python(),
            "stage_nlp.py",
            nlp_manifest,
            str(work / "nlp-result.json"),
            "nlp",
        )
        return [DocumentResult.from_dict(r) for r in nlp_results]
    except StageError as exc:
        log.error("NLP stage failed: %s", exc)
        return _fail_all([j["source"] for j in jobs], "nlp", str(exc))


def _run(
    sources: List[str], output_root: Path, suffix: str, work: Path
) -> List[DocumentResult]:
    plan: List[Dict[str, Any]] = []
    for index, source in enumerate(sources):
        stem = Path(source).stem + suffix
        plan.append(
            {
                "source": source,
                "spans": str(work / f"{index:05d}.spans.json"),
                "output_pdf": str(output_root / f"{stem}{output_extension(source)}"),
                "output_text": str(output_root / f"{stem}.txt"),
                "output_report": str(output_root / f"{stem}.report.json"),
            }
        )

    rasterisable = [j for j in plan if needs_ocr(j["source"])]
    text_only = [j for j in plan if not needs_ocr(j["source"])]

    ocr_status: Dict[str, Any] = {}

    if rasterisable:
        ocr_manifest = str(work / "ocr-manifest.json")
        write_manifest(
            ocr_manifest,
            [{"source": j["source"], "spans": j["spans"]} for j in rasterisable],
        )

        try:
            ocr_outcomes = _run_stage(
                ocr_python(),
                "stage_ocr.py",
                ocr_manifest,
                str(work / "ocr-result.json"),
                "ocr",
            )
        except StageError as exc:
            log.error("OCR stage failed: %s", exc)
            failures = _fail_all(
                [j["source"] for j in rasterisable], "ocr", str(exc)
            )
            if not text_only:
                return failures
            return failures + _run_nlp(text_only, work)

        ocr_status = {o["source"]: o for o in ocr_outcomes}

    # --- stage 2: PII detection + redaction ---------------------------
    ready = [
        j for j in rasterisable if ocr_status.get(j["source"], {}).get("status") == "ok"
    ] + text_only
    results = _run_nlp(ready, work)

    by_source = {r.source_path: r for r in results}

    # Reassemble in input order, filling in the files stage 1 rejected.
    ordered: List[DocumentResult] = []
    for job in plan:
        source = job["source"]
        if source in by_source:
            ordered.append(by_source[source])
            continue

        outcome = ocr_status.get(source, {})
        ordered.append(
            DocumentResult(
                source_path=source,
                status="error",
                error=outcome.get("error") or "OCR stage returned no result",
                failed_stage="ocr",
                duration_seconds=float(outcome.get("duration_seconds", 0.0)),
            )
        )

    return ordered


def preflight() -> List[str]:
    """Problems that would make a run fail, checked before doing work."""
    problems: List[str] = []

    for name, interpreter in (("ocr", ocr_python()), ("nlp", nlp_python())):
        if not os.path.isfile(interpreter):
            problems.append(
                f"{name} interpreter not found at '{interpreter}' "
                f"(set DEID_{name.upper()}_PYTHON)"
            )
        elif not os.access(interpreter, os.X_OK):
            problems.append(f"{name} interpreter '{interpreter}' is not executable")

    for script in ("stage_ocr.py", "stage_nlp.py"):
        path = OCR_ROOT / "scripts" / script
        if not path.is_file():
            problems.append(f"missing stage script {path}")

    problems.extend(model_store.missing_models(load_config()))

    return problems


def describe_environment() -> dict:
    """What the orchestrator resolved to -- printed by --preflight and worth having in a job log when something is misconfigured."""
    return {
        "orchestrator_python": sys.executable,
        "ocr_root": str(OCR_ROOT),
        "ocr_python": ocr_python(),
        "nlp_python": nlp_python(),
        "models": model_store.describe(load_config()),
    }
