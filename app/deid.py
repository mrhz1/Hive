"""De-identification orchestration.

This is the single place that knows how to de-identify a stored file, and
it is deliberately independent of *what* triggers it:

  * today  -- the API calls run_deidentification() in a FastAPI
              BackgroundTask when the user clicks De-identify
  * later  -- a Cloudera AI job runs scripts/deid_worker.py, which drains
              the pending queue by calling exactly the same function

Moving to the job model therefore changes scheduling, not logic.

The OCR/Presidio stack (paddle, torch, transformers, spacy) lives in its
own virtualenv and is invoked as a subprocess rather than imported. That
keeps ~3GB of ML dependencies out of the API process, and it is the same
shape the job will use -- a Cloudera job runs a script, not an import.
Only DEID_PYTHON changes between the two.
"""
import os
import subprocess
from pathlib import Path
from typing import Optional

import structlog

from app.crud import patient_files as crud
from app.db import hive_cursor
from app.logging_setup import get_logger
from app.schemas import PatientFileUpdate
from app.storage import resolve_stored_path

log = get_logger(__name__)

# Interpreter that has the OCR stack installed. On Cloudera AI point this
# at the runtime's python if the deps are baked into the image.
DEID_PYTHON = os.environ.get("DEID_PYTHON", "OCR/.venv/bin/python")
DEID_SCRIPT = os.environ.get("DEID_SCRIPT", "OCR/scripts/run_deid.py")

# OCR is slow (tens of seconds per page), so this is generous by design.
DEID_TIMEOUT_SECONDS = int(os.environ.get("DEID_TIMEOUT_SECONDS", "1800"))

# Must match run_deid.py's --suffix default, which is how the output file
# is named.
DEID_SUFFIX = os.environ.get("DEID_OUTPUT_SUFFIX", "_deid")

# Redacted copies go in a subfolder of the original's directory, so a
# patient's documents and their de-identified versions stay together.
DEID_SUBFOLDER = "deidentified"


class DeidError(Exception):
    """Raised internally so every failure path marks the row 'failed'."""


def _set_status(file_id: str, **fields) -> None:
    """Status writes get their own connection: they must land even when
    the main work has failed."""
    try:
        with hive_cursor() as cursor:
            crud.update_file(cursor, file_id, PatientFileUpdate(**fields))
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
        # The pipeline's own stderr is the useful part; truncate so a
        # stack trace does not end up as a giant Hive STRING.
        detail = (completed.stderr or completed.stdout or "").strip()[-500:]
        raise DeidError(f"De-identification failed (exit {completed.returncode}): {detail}")

    produced = output_dir / f"{source.stem}{DEID_SUFFIX}.pdf"
    if not produced.is_file():
        raise DeidError(f"De-identification produced no output at {produced}")

    return produced


def run_deidentification(file_id: str, request_id: Optional[str] = None) -> None:
    """De-identifies one stored file and records the result.

    Never raises: this runs detached from any request, so a failure is
    recorded on the row (deid_status='failed') and logged rather than
    surfacing as an unhandled background exception.
    """
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

    try:
        if record.file_extension.lower() != "pdf":
            raise DeidError(
                f"Only PDF files can be de-identified (got '{record.file_extension}')"
            )

        source = resolve_stored_path(record.file_path)
        if not source.is_file():
            raise DeidError("The stored file is missing from disk")

        produced = _run_pipeline(source, source.parent / DEID_SUBFOLDER)

        _set_status(
            file_id,
            deid_status="done",
            # The redacted copy is what no longer carries identifiers.
            is_identified=False,
            deidentified_file_name=produced.name,
            deidentified_file_path=str(produced),
        )
        log.info("deid_succeeded", file_id=file_id, output=str(produced))

    except DeidError as exc:
        # The reason goes to the log, not onto the row: `description` is
        # the user's own text and must not be clobbered. Add a dedicated
        # deid_error column if the reason needs surfacing in the UI.
        log.error("deid_failed", file_id=file_id, error=str(exc))
        _set_status(file_id, deid_status="failed")

    except Exception as exc:  # pragma: no cover - defensive
        log.exception("deid_crashed", file_id=file_id, error=str(exc))
        _set_status(file_id, deid_status="failed")
