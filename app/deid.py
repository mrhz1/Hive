"""De-identification orchestration."""
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import structlog

from app import deid_queue
from app.crud import patient_application_files as crud
from app.db import hive_cursor
from app.logging_setup import get_logger
from app.schemas import PatientApplicationFileUpdate
from app.storage import resolve_stored_path

log = get_logger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent

DEID_BACKEND = os.environ.get("DEID_BACKEND", "inline").strip().lower()

DEID_PYTHON = os.environ.get("DEID_PYTHON", sys.executable)
DEID_SCRIPT = os.environ.get(
    "DEID_SCRIPT", str(REPO_ROOT / "OCR" / "scripts" / "run_deid.py")
)

# OCR is slow (tens of seconds per page), so this is generous by design.
DEID_TIMEOUT_SECONDS = int(os.environ.get("DEID_TIMEOUT_SECONDS", "1800"))

DEID_SUFFIX = os.environ.get("DEID_OUTPUT_SUFFIX", "_deid")

DEID_SUBFOLDER = "deidentified"

DEID_OUTPUT_EXTENSIONS = {
    ".pdf": ".pdf",
    ".dcm": ".dcm",
    ".dicom": ".dcm",
    ".doc": ".docx",
    ".docx": ".docx",
}

DEIDENTIFIABLE_LABEL = "PDF, DICOM, Word"


def is_deidentifiable(extension: str) -> bool:
    return f".{(extension or '').lower().lstrip('.')}" in DEID_OUTPUT_EXTENSIONS


def deid_output_extension(extension: str) -> str:
    """The extension the pipeline will write for this input."""
    return DEID_OUTPUT_EXTENSIONS.get((extension or "").lower(), ".pdf")


class DeidError(Exception):
    """Raised internally so every failure path marks the row 'failed'."""


def _failure_detail(stderr: str, stdout: str) -> str:
    """The most useful ~500 characters of a failed run's output."""
    text = (stderr or stdout or "").strip()
    errors = [
        line
        for line in text.splitlines()
        if "ERROR" in line or "Traceback" in line or "Error:" in line
    ]
    detail = " | ".join(errors) if errors else text
    return detail.strip()[-500:]


def queued_status() -> str:
    """The status a freshly-queued file should be given."""
    return "queued" if DEID_BACKEND == "cml_job" else "processing"


def dispatch_deidentification(
    file_id: str, request_id: Optional[str] = None
) -> None:
    """Start de-identification by whichever route is configured."""
    if DEID_BACKEND == "inline":
        run_deidentification(file_id, request_id=request_id)
        return

    if DEID_BACKEND != "cml_job":
        log.error("deid_backend_unknown", backend=DEID_BACKEND, file_id=file_id)
        _set_status(file_id, deid_status="failed")
        return

    if request_id:
        structlog.contextvars.bind_contextvars(
            request_id=request_id, background_task="deidentify_dispatch"
        )

    deid_queue.request_dispatch()
    log.info("deid_job_enqueued", file_id=file_id)


def _set_status(file_id: str, **fields) -> None:
    """Status writes get their own connection: they must land even when the main work has failed."""
    try:
        with hive_cursor() as cursor:
            crud.update_file(cursor, file_id, PatientApplicationFileUpdate(**fields))
    except Exception as exc:  # pragma: no cover - last-resort logging
        log.error("deid_status_write_failed", file_id=file_id, error=str(exc))


def _run_pipeline(source: Path, output_dir: Path) -> Path:
    """Invokes the OCR job for one file and returns the redacted PDF."""
    output_dir.mkdir(parents=True, exist_ok=True)

    command = [
        DEID_PYTHON,
        DEID_SCRIPT,
        "--input",
        str(source),
        "--output-dir",
        str(output_dir),
        "--suffix",
        DEID_SUFFIX,
    ]

    log.info("deid_subprocess_start", command=" ".join(command))

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=DEID_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as exc:
        raise DeidError(
            f"De-identification runtime not found at '{DEID_PYTHON}'. "
            "Set DEID_PYTHON to an interpreter with the OCR stack installed."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise DeidError(
            f"De-identification timed out after {DEID_TIMEOUT_SECONDS}s"
        ) from exc

    if completed.returncode != 0:
        log.error(
            "deid_subprocess_failed",
            returncode=completed.returncode,
            stderr=(completed.stderr or "").strip(),
            stdout=(completed.stdout or "").strip(),
        )
        detail = _failure_detail(completed.stderr, completed.stdout)
        raise DeidError(f"De-identification failed (exit {completed.returncode}): {detail}")

    produced = output_dir / f"{source.stem}{DEID_SUFFIX}{deid_output_extension(source.suffix)}"
    if not produced.is_file():
        raise DeidError(f"De-identification produced no output at {produced}")

    return produced


def run_deidentification(file_id: str, request_id: Optional[str] = None) -> None:
    """De-identifies one stored file and records the result."""
    if request_id:
        structlog.contextvars.bind_contextvars(
            request_id=request_id, background_task="deidentify"
        )

    try:
        with hive_cursor() as cursor:
            record = crud.get_file_or_404(cursor, file_id)
    except Exception as exc:
        log.error("deid_lookup_failed", file_id=file_id, error=str(exc))
        return

    log.info("deid_started", file_id=file_id, name=record.sanitized_file_name)

    if record.deid_status != "processing":
        _set_status(file_id, deid_status="processing")

    try:
        if not is_deidentifiable(record.file_extension):
            raise DeidError(
                f"'{record.file_extension}' cannot be de-identified "
                f"(handled: {DEIDENTIFIABLE_LABEL})"
            )

        source = resolve_stored_path(record.file_path)
        if not source.is_file():
            raise DeidError("The stored file is missing from disk")

        produced = _run_pipeline(source, source.parent / DEID_SUBFOLDER)

        _set_status(
            file_id,
            deid_status="done",
            # The redacted copy is what no longer carries identifiers.
            is_deidentified=True,
            deidentified_file_name=produced.name,
            de_identified_file_path=str(produced),
        )
        log.info("deid_succeeded", file_id=file_id, output=str(produced))

    except DeidError as exc:
        log.error("deid_failed", file_id=file_id, error=str(exc))
        _set_status(file_id, deid_status="failed")

    except Exception as exc:  # pragma: no cover - defensive
        log.exception("deid_crashed", file_id=file_id, error=str(exc))
        _set_status(file_id, deid_status="failed")
