"""Orchestration across two virtualenvs.

## Why the pipeline is split

PaddleOCR and Presidio cannot be installed into the same environment.
The conflict is exact and unfixable from our side:

    paddleocr -> paddlex           pins  PyYAML==6.0.2
    presidio-analyzer >= 2.2.363   needs pyyaml>=6.0.3

so pip has no solution. Pinning presidio back to 2.2.362 does resolve
today, but it freezes de-identification -- the part of this system with
actual compliance consequences -- at whatever version happens to predate
the clash, and it breaks again on the next release of either package.
Beyond the metadata, the two stacks each ship their own OpenMP runtime
and a ~3GB torch install that the OCR half has no use for.

So the stages run as two processes with two virtualenvs:

    stage 1  .venv-ocr   paddleocr + paddlepaddle + PyMuPDF   -> spans JSON
    stage 2  .venv-nlp   presidio + transformers + PyMuPDF    -> redacted PDF

This module is the coordinator. It runs under *neither* of those: it is
standard library only, so the Cloudera AI runtime's stock python can
execute it with nothing installed.

## The handoff

Stage 1 writes one JSON file per PDF holding the recognised text and its
pixel geometry (deid/spans.py). Stage 2 reads it, detects PII, and
redacts the original PDF.

That file contains raw OCR text, so **it is PHI**. It lives in a 0700
temp directory that is removed in a `finally`, and it is written 0600.
DEID_KEEP_WORK_DIR exists for debugging a bad redaction and must stay off
in production.

## Failure handling

Stage 1 failures are recorded per file and stage 2 is simply not asked to
process them. A stage crashing outright (missing interpreter, OOM) fails
every file in its batch with the stage named, because at that point we
cannot tell which file was to blame.
"""
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
from deid.spans import write_manifest

log = logging.getLogger(__name__)

# The OCR package root, so every default path works regardless of the
# process's working directory -- a Cloudera job does not necessarily
# start where you think it does.
OCR_ROOT = Path(__file__).resolve().parent.parent

# Interpreters for the two stages. Defaults point at the venvs the
# Makefile builds; on Cloudera AI set them to wherever the environment
# build put them (they must be absolute there).
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
    """The most useful ~800 characters of a failed stage's output.

    Prefers the lines the stage logged at ERROR over the raw tail. A
    stage's stderr opens with the ML stack's import chatter -- paddle
    warns "No ccache found" on every run, successful ones included -- so
    the tail alone can be pure noise that reads like the cause.
    """
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
    """Run one stage subprocess and read back its result file.

    Results come from a file rather than stdout because the ML stacks
    print to stdout at import time -- paddle in particular -- and mixing
    that into a JSON payload makes the parse fail in a way that looks
    like a pipeline bug.
    """
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
            # The stages inherit the environment: OCR_*/DEID_* config vars
            # are read inside them, and PATH/HF_HOME matter for model
            # resolution.
            env=os.environ.copy(),
        )
    except FileNotFoundError as exc:
        raise StageError(
            f"{stage} stage interpreter not found at '{interpreter}'. "
            f"Set DEID_{stage.upper()}_PYTHON to the venv that has the "
            f"{stage} dependencies installed."
        ) from exc

    if completed.stderr and (completed.returncode != 0 or _log_stage_output()):
        # Forwarded only on failure, because a stage's stderr can quote
        # the document: warnings from the NLP libraries embed the text
        # they choked on, which is patient text. Copying that into a
        # Cloudera job log would re-leak exactly what this pipeline
        # removes. On failure the diagnostic is worth the risk; routinely
        # it is not. DEID_LOG_STAGE_OUTPUT forces it on for debugging.
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
    """De-identify every PDF in `sources`, writing results to `output_dir`.

    Returns one DocumentResult per input, in input order.
    """
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
        # mkdtemp is 0700 by default, which is what we want for a
        # directory about to hold OCR'd patient text.
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


def _run(
    sources: List[str], output_root: Path, suffix: str, work: Path
) -> List[DocumentResult]:
    # Index-prefixed names, because two inputs in different directories
    # can share a basename and would otherwise overwrite each other's
    # handoff file.
    plan: List[Dict[str, Any]] = []
    for index, source in enumerate(sources):
        stem = Path(source).stem + suffix
        plan.append(
            {
                "source": source,
                "spans": str(work / f"{index:05d}.spans.json"),
                "output_pdf": str(output_root / f"{stem}.pdf"),
                "output_text": str(output_root / f"{stem}.txt"),
                "output_report": str(output_root / f"{stem}.report.json"),
            }
        )

    # --- stage 1: OCR ------------------------------------------------
    ocr_manifest = str(work / "ocr-manifest.json")
    write_manifest(
        ocr_manifest, [{"source": j["source"], "spans": j["spans"]} for j in plan]
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
        return _fail_all([j["source"] for j in plan], "ocr", str(exc))

    ocr_status = {o["source"]: o for o in ocr_outcomes}

    # --- stage 2: PII detection + redaction ---------------------------
    ready = [j for j in plan if ocr_status.get(j["source"], {}).get("status") == "ok"]
    results: List[DocumentResult] = []

    if ready:
        nlp_manifest = str(work / "nlp-manifest.json")
        write_manifest(nlp_manifest, ready)
        try:
            nlp_results = _run_stage(
                nlp_python(),
                "stage_nlp.py",
                nlp_manifest,
                str(work / "nlp-result.json"),
                "nlp",
            )
            results = [DocumentResult.from_dict(r) for r in nlp_results]
        except StageError as exc:
            log.error("NLP stage failed: %s", exc)
            results = _fail_all([j["source"] for j in ready], "nlp", str(exc))

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
    """Problems that would make a run fail, checked before doing work.

    Worth having as its own step: the failure mode without it is a job
    that spends a minute loading models and then dies on a missing path.
    """
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

    # Weights are checked here, in the dependency-free orchestrator,
    # precisely because the stages cannot check them cheaply: finding out
    # that the NER model is missing costs a python start plus a torch
    # import first. A missing model directory is also the expected
    # failure on Cloudera AI, where the store arrives by file copy and
    # nothing downloads it if the copy was incomplete.
    problems.extend(model_store.missing_models(load_config()))

    return problems


def describe_environment() -> dict:
    """What the orchestrator resolved to -- printed by --preflight and
    worth having in a job log when something is misconfigured."""
    return {
        "orchestrator_python": sys.executable,
        "ocr_root": str(OCR_ROOT),
        "ocr_python": ocr_python(),
        "nlp_python": nlp_python(),
        "models": model_store.describe(load_config()),
    }
