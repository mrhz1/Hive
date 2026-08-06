"""De-identification orchestration.

This is the single place that knows how to de-identify a stored file, and
it is deliberately independent of *what* triggers it:

  * `DEID_BACKEND=inline`  -- the API calls run_deidentification() in a
    FastAPI BackgroundTask when the user clicks De-identify. Fine locally
    and at low volume.
  * `DEID_BACKEND=cml_job` -- the API only marks the row `pending` and
    asks Cloudera AI to start the de-identification Job, which runs
    scripts/deid_worker.py and calls exactly the same function.

Switching therefore changes *scheduling*, not logic.

The OCR/Presidio stack is invoked as a subprocess, never imported, so
~3GB of ML dependencies stay out of the API process. Note that the stack
is itself split across two virtualenvs -- paddle and presidio cannot be
installed together -- but that is entirely OCR/scripts/run_deid.py's
problem: it is standard-library-only and coordinates the two. See
OCR/deid/pipeline.py. Which is why DEID_PYTHON below defaults to *this*
interpreter: the orchestrator needs nothing installed.
"""
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import structlog

from app.cloudera import ClouderaError, start_deid_job_run
from app.crud import patient_files as crud
from app.db import hive_cursor
from app.logging_setup import get_logger
from app.schemas import PatientFileUpdate
from app.storage import resolve_stored_path

log = get_logger(__name__)

# Absolute, derived from this file, so nothing depends on the process's
# working directory -- a Cloudera Application does not necessarily start
# where you think it does, and the old relative defaults broke silently
# when it did not.
REPO_ROOT = Path(__file__).resolve().parent.parent

# "inline" runs the pipeline in this process's background task;
# "cml_job" hands off to the Cloudera AI Job. Configuration, not an
# environment check -- the code path is chosen by value, not by sniffing
# for CDSW_* vars.
DEID_BACKEND = os.environ.get("DEID_BACKEND", "inline").strip().lower()

# The orchestrator is stdlib-only, so the API's own interpreter can run
# it. Override only if the OCR tree lives under a different python.
DEID_PYTHON = os.environ.get("DEID_PYTHON", sys.executable)
DEID_SCRIPT = os.environ.get(
    "DEID_SCRIPT", str(REPO_ROOT / "OCR" / "scripts" / "run_deid.py")
)

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


def queued_status() -> str:
    """The status a freshly-queued file should be given.

    Inline runs mark `processing` immediately, because the work begins in
    this process a moment later. The Cloudera Job backend marks `queued`:
    the run has been *asked for* but no worker has claimed the row yet,
    and marking `processing` before anything is processing it would leave
    a permanently stuck row if the run never starts. It cannot use
    `pending` either -- that is the state every file is uploaded in, so
    it carries no information about whether anyone asked.
    """
    return "queued" if DEID_BACKEND == "cml_job" else "processing"


def dispatch_deidentification(
    file_id: str, request_id: Optional[str] = None
) -> None:
    """Start de-identification by whichever route is configured.

    Runs as a background task in both modes: the inline path does minutes
    of work, and the cml_job path makes a network call to the control
    plane that must not sit in the user's request.

    Never raises, for the same reason run_deidentification does not --
    there is no request left to return an error to.
    """
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

    try:
        # DEID_FILE_ID scopes the run to this file. The worker still
        # drains anything else left pending, so a dropped trigger is
        # recovered by the next run rather than stranding a row.
        run_id = start_deid_job_run(environment={"DEID_FILE_ID": file_id})
        log.info("deid_job_dispatched", file_id=file_id, run_id=run_id)
    except ClouderaError as exc:
        log.error("deid_job_dispatch_failed", file_id=file_id, error=str(exc))
        _set_status(file_id, deid_status="failed")


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

    # Claim the row here rather than relying on the caller. The API marks
    # it before dispatch, but a Job run started on a schedule picks up
    # rows nobody marked -- and a file that is genuinely being worked on
    # for the next several minutes must not still read as 'queued'.
    if record.deid_status != "processing":
        _set_status(file_id, deid_status="processing")

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
            is_deidentified=True,
            de_identified_file_name=produced.name,
            de_identified_file_path=str(produced),
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
