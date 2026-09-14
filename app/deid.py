import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

import structlog

from app import deid_notices
from app import deid_progress
from app import deid_queue
from app.crud import patient_application_files as crud
from app.crud import patient_applications as applications_crud
from app.db import hive_cursor
from app.embed import embed_metadata, generated_facts
from app.ids import new_document_serial
from app.logging_setup import get_logger
from app.schemas import PatientApplicationFileUpdate
from app.storage import (
    delete_file as remove_from_disk,
    document_name,
    document_type_for,
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

DEID_TIMEOUT_SECONDS = int(os.environ.get("DEID_TIMEOUT_SECONDS", "5400"))

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
    return DEID_OUTPUT_EXTENSIONS.get((extension or "").lower(), ".pdf")


NAME_ATTEMPTS = 5


def deid_output_stem(patient_id: str, extension: str) -> str:
    """`<patient code>-<type>-<date>-<16-digit serial>_deid`.

    The date and the serial are the redaction run's own, not the original
    upload's: a re-run is a new document, and reading the name tells you
    when the redacted copy was made rather than when the scan arrived.
    """
    stem = document_name(
        patient_id or "unknown",
        document_type_for(extension),
        new_document_serial(),
        "",
    )
    return f"{stem}{DEID_SUFFIX}"


def deid_output_name(patient_id: str, extension: str) -> str:
    suffix = (extension or "").lower().lstrip(".")
    stem = deid_output_stem(patient_id, suffix)
    return f"{stem}.{suffix}" if suffix else stem


def _free_output_stem(directory: Path, patient_id: str, extension: str) -> str:
    stem = deid_output_stem(patient_id, extension)

    for _ in range(NAME_ATTEMPTS):
        if not any(directory.glob(f"{stem}*")):
            return stem
        stem = deid_output_stem(patient_id, extension)

    log.warning("deid_output_stem_contested", stem=stem, directory=str(directory))
    return stem


def _resolved_or_none(stored: str) -> Optional[Path]:
    try:
        return resolve_stored_path(stored)
    except Exception:
        return None


def deid_artifacts(source_stored_path: str, deidentified_name: str = "") -> List[Path]:
    source = _resolved_or_none(source_stored_path)
    if source is None:
        return []

    output_dir = source.parent / DEID_SUBFOLDER
    if not output_dir.is_dir():
        return []

    # A run names its outputs after itself, so the recorded name is what finds
    # them. The source-derived prefix is still tried, for rows written before
    # that and for a run that died before it could record anything.
    prefixes = [f"{source.stem}{DEID_SUFFIX}"]
    if deidentified_name:
        prefixes.append(Path(deidentified_name).stem)

    try:
        return sorted(
            path
            for path in output_dir.iterdir()
            if path.is_file() and path.name.startswith(tuple(prefixes))
        )
    except OSError as exc:  # pragma: no cover - unreadable directory
        log.warning("deid_artifact_scan_failed", directory=str(output_dir), error=str(exc))
        return []


def remove_deid_artifacts(source_stored_path: str, deidentified_name: str = "") -> int:
    removed = 0
    for path in deid_artifacts(source_stored_path, deidentified_name):
        remove_from_disk(str(path))
        removed += 1

    if removed:
        log.info(
            "deid_artifacts_removed", source=source_stored_path, count=removed
        )

    source = _resolved_or_none(source_stored_path)
    if source is not None:
        prune_empty_dirs(source.parent / DEID_SUBFOLDER)

    return removed


class DeidError(Exception):
    pass


def _signal_name(returncode: int) -> str:
    if returncode >= 0:
        return ""
    try:
        return signal.Signals(-returncode).name
    except ValueError:
        return f"signal {-returncode}"


def _exit_description(returncode: int) -> str:
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
    text = (stderr or stdout or "").strip()
    errors = [
        line
        for line in text.splitlines()
        if "ERROR" in line or "Traceback" in line or "Error:" in line
    ]
    detail = " | ".join(errors) if errors else text
    return detail.strip()[-500:]


def queued_status() -> str:
    return "queued" if DEID_BACKEND == "cml_job" else "processing"


def dispatch_deidentification(
    file_id: str, request_id: Optional[str] = None
) -> None:
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
    try:
        with hive_cursor() as cursor:
            crud.update_file(cursor, file_id, PatientApplicationFileUpdate(**fields))
    except Exception as exc:  # pragma: no cover - last-resort logging
        log.error("deid_status_write_failed", file_id=file_id, error=str(exc))


def _run_pipeline(source: Path, output_dir: Path, file_id: str = "") -> Path:
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

    if file_id:
        command += ["--progress-file", str(deid_progress.progress_path(file_id))]

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


def _patient_id_of(record) -> str:
    try:
        with hive_cursor() as cursor:
            return _patient_id_for(cursor, record.application_id)
    except Exception as exc:
        log.warning("deid_patient_lookup_failed", file_id=record.id, error=str(exc))
        return ""


def _rename_run_outputs(produced: Path, patient_id: str) -> Path:
    """Rename a run's outputs to the de-identified naming scheme.

    The pipeline names what it writes after the file it read, which would
    leave the original's upload date and serial on the redacted copy.
    Everything the run produced for this document shares one stem -- the
    copy, the extracted text and the report -- so they move together and
    stay findable as a set.
    """
    old_stem = produced.stem
    new_stem = _free_output_stem(produced.parent, patient_id, produced.suffix)
    if new_stem == old_stem:
        return produced

    target = produced.with_name(f"{new_stem}{produced.suffix}")
    try:
        produced.rename(target)
    except OSError as exc:
        # The right bytes under the wrong name is still a good run, so keep
        # it rather than failing the file over a rename.
        log.warning(
            "deid_output_rename_failed",
            source=str(produced),
            target=str(target),
            error=str(exc),
        )
        return produced

    for path in sorted(produced.parent.iterdir()):
        if not path.is_file() or not path.name.startswith(old_stem):
            continue
        try:
            path.rename(path.with_name(new_stem + path.name[len(old_stem):]))
        except OSError as exc:  # pragma: no cover - best effort
            log.warning(
                "deid_sidecar_rename_failed", source=str(path), error=str(exc)
            )

    log.info("deid_output_named", name=target.name, produced_as=produced.name)
    return target


def _record_deid_metadata(record, produced: Path, patient_id: Optional[str] = None) -> None:
    output_type = produced.suffix.lstrip(".").lower()

    if patient_id is None:
        patient_id = _patient_id_of(record)

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

        produced = _run_pipeline(source, source.parent / DEID_SUBFOLDER, file_id)

        patient_id = _patient_id_of(record)
        produced = _rename_run_outputs(produced, patient_id)

        _set_status(
            file_id,
            deid_status="done",
            is_deidentified=True,
            deidentified_file_name=produced.name,
            de_identified_file_path=str(produced),
        )
        _record_deid_metadata(record, produced, patient_id)
        log.info("deid_succeeded", file_id=file_id, output=str(produced))

    except DeidError as exc:
        log.error("deid_failed", file_id=file_id, error=str(exc))
        _set_status(file_id, deid_status="failed")

    except Exception as exc:  # pragma: no cover - defensive
        log.exception("deid_crashed", file_id=file_id, error=str(exc))
        _set_status(file_id, deid_status="failed")

    finally:
        deid_progress.clear(file_id)

    deid_notices.notify_if_finished(record.application_id)
