"""De-identification orchestration."""
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

import structlog

from app import deid_queue
from app.crud import patient_application_files as crud
from app.crud import patient_applications as applications_crud
from app.db import hive_cursor
from app.embed import embed_metadata, generated_facts
from app.logging_setup import get_logger
from app.schemas import PatientApplicationFileUpdate
from app.storage import (
    delete_file as remove_from_disk,
    prune_empty_dirs,
    resolve_stored_path,
)

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


def _resolved_or_none(stored: str) -> Optional[Path]:
    """The path, or nothing. Cleanup must not raise on the way past."""
    try:
        return resolve_stored_path(stored)
    except Exception:
        # Outside the storage root, or unreadable -- the same judgement
        # delete_file makes.
        return None


def deid_artifacts(source_stored_path: str) -> List[Path]:
    """Everything a de-identification run wrote for one source document.

    The redacted document is only one of three: the pipeline also writes
    `<stem>_deid.txt` -- the text it read out of the file -- and
    `<stem>_deid.report.json`, saying what it found and redacted. Only
    the first is moved out and recorded on the row, so those two are the
    ones nothing else knows about, and deleting a document used to leave
    them behind: the extracted text of a document that no longer exists,
    sitting in the upload folder with nothing pointing at it.

    Matched by name rather than globbed, because a stem comes from a
    file name and `[` in one would quietly change what a glob means.
    """
    source = _resolved_or_none(source_stored_path)
    if source is None:
        return []

    output_dir = source.parent / DEID_SUBFOLDER
    if not output_dir.is_dir():
        return []

    prefix = f"{source.stem}{DEID_SUFFIX}"
    try:
        return sorted(
            path
            for path in output_dir.iterdir()
            if path.is_file() and path.name.startswith(prefix)
        )
    except OSError as exc:  # pragma: no cover - unreadable directory
        log.warning("deid_artifact_scan_failed", directory=str(output_dir), error=str(exc))
        return []


def remove_deid_artifacts(source_stored_path: str) -> int:
    """Delete a run's leftovers, and the folder if it held nothing else."""
    removed = 0
    for path in deid_artifacts(source_stored_path):
        remove_from_disk(str(path))
        removed += 1

    if removed:
        log.info(
            "deid_artifacts_removed", source=source_stored_path, count=removed
        )

    source = _resolved_or_none(source_stored_path)
    if source is not None:
        # Attempted even when there was nothing to remove: submission
        # moves the redacted document out, and what it leaves behind is
        # this folder with nothing in it. prune_empty_dirs stops the
        # moment a directory is not empty, so another document's outputs
        # in here keep it -- and the upload folder above it -- exactly
        # as they are.
        prune_empty_dirs(source.parent / DEID_SUBFOLDER)

    return removed


class DeidError(Exception):
    """Raised internally so every failure path marks the row 'failed'."""


def _signal_name(returncode: int) -> str:
    """The signal that killed the run, when one did.

    subprocess reports a signal death as a negative return code, so -9
    is SIGKILL. Nothing in the pipeline sends itself a signal, which
    leaves the platform: SIGKILL almost always means the workload was
    killed for using more memory than it was given.
    """
    if returncode >= 0:
        return ""
    try:
        return signal.Signals(-returncode).name
    except ValueError:
        return f"signal {-returncode}"


def _exit_description(returncode: int) -> str:
    """How the run ended, in terms somebody can act on."""
    name = _signal_name(returncode)
    if not name:
        return f"exit {returncode}"

    if returncode == -9:
        return (
            "killed by SIGKILL -- almost always the platform stopping it for "
            "running out of memory. OCR and the NLP models are the memory "
            "cost here, so give the Job more, or feed it smaller documents"
        )

    return f"killed by {name}"


def _failure_detail(stderr: str, stdout: str) -> str:
    """The most useful ~500 characters of a failed run's output.

    Error lines only, where there are any. That is not just for brevity:
    the NLP stage's dependencies quote the document into their warnings
    (`UserWarning: Skipping annotation ... for doc '<the document>'`),
    so forwarding a failed run's output wholesale puts patient names in
    the log -- re-leaking exactly what the pipeline removed. See the
    gotchas in OCR/README.md.
    """
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
        detail = _failure_detail(completed.stderr, completed.stdout)
        # Filtered and bounded, never the raw streams -- see _failure_detail.
        log.error(
            "deid_subprocess_failed",
            returncode=completed.returncode,
            signal=_signal_name(completed.returncode),
            detail=detail,
        )
        raise DeidError(
            f"De-identification failed ({_exit_description(completed.returncode)})"
            + (f": {detail}" if detail else "")
        )

    produced = output_dir / f"{source.stem}{DEID_SUFFIX}{deid_output_extension(source.suffix)}"
    if not produced.is_file():
        raise DeidError(f"De-identification produced no output at {produced}")

    return produced


def _patient_id_for(cursor, application_id: str) -> str:
    application = applications_crud.get_application(cursor, application_id)
    return getattr(application, "patient_id", "") or ""


def _record_deid_metadata(record, produced: Path) -> None:
    """Write what came out of de-identification into the output file.

    Deliberately not into `file_metadata`: that row holds what the
    *original* arrived carrying, and mixing our own facts into it made
    the two indistinguishable once stored. See app/embed.py.
    """
    output_type = produced.suffix.lstrip(".").lower()

    try:
        with hive_cursor() as cursor:
            patient_id = _patient_id_for(cursor, record.application_id)
    except Exception as exc:
        log.warning("deid_patient_lookup_failed", file_id=record.id, error=str(exc))
        patient_id = ""

    embed_metadata(
        produced,
        output_type,
        generated_facts(
            patient_id=patient_id,
            output_name=produced.name,
            output_type=output_type,
        ),
    )


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
        _record_deid_metadata(record, produced)
        log.info("deid_succeeded", file_id=file_id, output=str(produced))

    except DeidError as exc:
        log.error("deid_failed", file_id=file_id, error=str(exc))
        _set_status(file_id, deid_status="failed")

    except Exception as exc:  # pragma: no cover - defensive
        log.exception("deid_crashed", file_id=file_id, error=str(exc))
        _set_status(file_id, deid_status="failed")
