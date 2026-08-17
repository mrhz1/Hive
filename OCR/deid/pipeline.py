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
from deid.progress import writer as progress_writer
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


def ocr_batch_size() -> int:
    """How many documents one OCR process handles at a time.

    One by default. Rasterising and reading a page is where the memory
    goes, so this is the dial between speed and surviving: raise it on a
    workload with memory to spare, leave it alone on one that gets its
    OCR process killed.
    """
    try:
        return max(1, int(os.environ.get("DEID_OCR_BATCH_SIZE", "1")))
    except ValueError:
        return 1


def _batched(items: List[Any], size: int):
    for start in range(0, len(items), size):
        yield items[start : start + size]


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
    progress_path: Optional[str] = None,
) -> List[DocumentResult]:
    """De-identify every PDF in `sources`, writing results to `output_dir`.

    `progress_path` is a file the stages rewrite as they advance. It must
    live somewhere the caller can read -- the work dir will not do, that
    is this container's /tmp. See deid/progress.py.
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
        work = Path(tempfile.mkdtemp(prefix="deid-work-"))
        owned = True

    try:
        return _run(sources, output_root, suffix, work, progress_path)
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
    sources: List[str],
    output_root: Path,
    suffix: str,
    work: Path,
    progress_path: Optional[str] = None,
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
                # Carried into both manifests: a stage subprocess has no
                # other way to learn where to report, and `index`/`total`
                # are what keep the bar continuous across a batch.
                "progress": progress_path,
                "index": index,
                "file_total": len(sources),
            }
        )

    rasterisable = [j for j in plan if needs_ocr(j["source"])]
    text_only = [j for j in plan if not needs_ocr(j["source"])]

    ocr_status: Dict[str, Any] = {}

    ocr_failures: List[DocumentResult] = []

    if rasterisable:
        # In batches, because peak memory follows the batch. Rendering a
        # page to an image and running OCR over it is the expensive part
        # of this whole pipeline, and handing one process every document
        # at once is what gets it killed -- exit -9, no result file, the
        # whole batch lost. One application's worth of documents fitted;
        # several did not. Smaller batches take marginally longer and
        # survive, and a batch that does die costs only its own
        # documents rather than all of them.
        outcomes: List[dict] = []

        for index, batch in enumerate(_batched(rasterisable, ocr_batch_size())):
            manifest = str(work / f"ocr-manifest-{index:03d}.json")
            write_manifest(
                manifest,
                [
                    {
                        "source": j["source"],
                        "spans": j["spans"],
                        "progress": j["progress"],
                        "index": j["index"],
                        "file_total": j["file_total"],
                    }
                    for j in batch
                ],
            )

            try:
                outcomes.extend(
                    _run_stage(
                        ocr_python(),
                        "stage_ocr.py",
                        manifest,
                        str(work / f"ocr-result-{index:03d}.json"),
                        "ocr",
                    )
                )
            except StageError as exc:
                log.error(
                    "OCR stage failed for %d of %d document(s): %s",
                    len(batch),
                    len(rasterisable),
                    exc,
                )
                ocr_failures.extend(
                    _fail_all([j["source"] for j in batch], "ocr", str(exc))
                )

        ocr_status = {o["source"]: o for o in outcomes}

    # --- stage 2: PII detection + redaction ---------------------------
    ready = [
        j for j in rasterisable if ocr_status.get(j["source"], {}).get("status") == "ok"
    ] + text_only
    results = _run_nlp(ready, work)

    by_source = {r.source_path: r for r in results}
    # A batch that died takes its documents with it, and its error says
    # how -- 'exit -9', which is the one detail worth keeping.
    failed_batches = {r.source_path: r for r in ocr_failures}

    # Reassemble in input order, filling in the files stage 1 rejected.
    ordered: List[DocumentResult] = []
    for job in plan:
        source = job["source"]
        if source in by_source:
            ordered.append(by_source[source])
            continue

        if source in failed_batches:
            ordered.append(failed_batches[source])
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

    # The stages cannot write the terminal state themselves: a stage that
    # is killed (exit -9) writes nothing at all, and the reader would sit
    # on a stale "ocr, page 41 of 100" forever. The orchestrator outlives
    # both, so it is what closes the file out.
    progress = progress_writer(progress_path, file_total=len(plan)).adopt()
    failures = [r for r in ordered if r.status != "ok"]
    if failures and len(failures) == len(ordered):
        progress.fail(failures[0].error or "de-identification failed")
    else:
        progress.finish()

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
