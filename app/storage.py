"""Filesystem storage for application documents."""
import mimetypes
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from app.errors import ValidationError
from app.ids import new_document_serial
from app.logging_setup import get_logger
from app.schemas import METADATA_EXTENSIONS

log = get_logger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent

STORAGE_ROOT = Path(os.environ.get("FILE_STORAGE_DIR", "storage/patient_files"))
if not STORAGE_ROOT.is_absolute():
    STORAGE_ROOT = REPO_ROOT / STORAGE_ROOT

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_NAME = 120


def sanitize_filename(name: str) -> str:
    """Make an arbitrary upload name safe to place on disk."""
    base = re.split(r"[\\/]", name)[-1].strip()

    normalised = unicodedata.normalize("NFKD", base)
    ascii_only = normalised.encode("ascii", "ignore").decode("ascii")
    cleaned = _UNSAFE.sub("_", ascii_only).strip("._-")

    if not cleaned:
        cleaned = "file"

    stem, dot, suffix = cleaned.rpartition(".")
    if dot:
        stem = stem[: _MAX_NAME - len(suffix) - 1] or "file"
        return f"{stem}.{suffix}"
    return cleaned[:_MAX_NAME]


def file_extension(name: str) -> str:
    """Lowercased extension without the dot, '' when there is none."""
    suffix = Path(name).suffix
    return suffix[1:].lower() if suffix else ""


def guess_mime_type(name: str, provided: str | None) -> str:
    """Trust the browser when it says something specific, else infer."""
    if provided and provided != "application/octet-stream":
        return provided
    guessed, _ = mimetypes.guess_type(name)
    return guessed or "application/octet-stream"


def application_dir(application_id: str) -> Path:
    return STORAGE_ROOT / application_id


RECEIVED_FORMAT = "%Y%m%dT%H%M%SZ"

_SERIAL_ATTEMPTS = 5


def patient_dir(patient_id: str, received_at: datetime) -> Path:
    """<patient id>-<time received>, one folder per upload batch."""
    return STORAGE_ROOT / f"{patient_id}-{received_at.strftime(RECEIVED_FORMAT)}"


def document_type_for(extension: str) -> str:
    """'pdf' / 'dicom' / 'word' for the formats we know, else the extension."""
    known = METADATA_EXTENSIONS.get((extension or "").lower().lstrip("."))
    if known:
        return known

    fallback = _UNSAFE.sub("", (extension or "").lower())
    return fallback or "file"


def document_name(
    patient_id: str, document_type: str, serial: str, extension: str
) -> str:
    suffix = f".{extension.lower()}" if extension else ""
    return f"{patient_id}-{document_type}-{serial}{suffix}"


def write_patient_document(
    patient_id: str,
    extension: str,
    data: bytes,
    received_at: datetime,
) -> Path:
    """Store one upload under the patient naming scheme."""
    directory = patient_dir(patient_id, received_at)
    directory.mkdir(parents=True, exist_ok=True)

    document_type = document_type_for(extension)

    for _ in range(_SERIAL_ATTEMPTS):
        serial = new_document_serial()
        target = directory / document_name(
            patient_id, document_type, serial, extension
        )
        if not target.exists():
            break
    else:
        raise ValidationError("Could not allocate a unique document serial")

    target.write_bytes(data)
    log.info(
        "file_stored",
        patient_id=patient_id,
        document_type=document_type,
        path=str(target),
        bytes=len(data),
    )
    return target


def write_file(
    application_id: str, file_id: str, sanitized_name: str, data: bytes
) -> Path:
    """Legacy layout, kept for uploads whose patient cannot be resolved."""
    directory = application_dir(application_id)
    directory.mkdir(parents=True, exist_ok=True)

    target = directory / f"{file_id}_{sanitized_name}"
    target.write_bytes(data)
    log.info(
        "file_stored",
        application_id=application_id,
        file_id=file_id,
        path=str(target),
        bytes=len(data),
    )
    return target


def resolve_stored_path(stored: str) -> Path:
    """Resolve a path read back from Hive, refusing anything outside the storage root."""
    root = STORAGE_ROOT.resolve()

    raw = Path(stored)
    candidate = (raw if raw.is_absolute() else REPO_ROOT / raw).resolve()

    if candidate.is_relative_to(root):
        return candidate

    tail = Path(*raw.parts[-2:]) if len(raw.parts) >= 2 else None
    if tail is not None:
        rehomed = (root / tail).resolve()
        # Re-check: '..' in the stored value must not survive the join.
        if rehomed.is_relative_to(root) and rehomed.exists():
            log.info("file_path_rehomed", stored=stored, resolved=str(rehomed))
            return rehomed

    log.error("file_path_outside_storage_root", path=stored, storage_root=str(root))
    raise ValidationError("Stored file path is outside the storage root")


def delete_file(stored: str) -> None:
    """Best effort: a missing file must not block deleting its row."""
    try:
        resolve_stored_path(stored).unlink(missing_ok=True)
    except Exception as exc:  # pragma: no cover - cleanup is not critical
        log.warning("file_delete_failed", path=stored, error=str(exc))
