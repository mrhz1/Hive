"""Filesystem storage for application documents."""
import mimetypes
import os
import re
import shutil
import unicodedata
from datetime import datetime
from pathlib import Path

from app.errors import ValidationError
from app.ids import new_document_serial
from app.logging_setup import get_logger
from app.schemas import METADATA_EXTENSIONS

log = get_logger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent

def _configured_dir(name: str, default: str) -> Path:
    """An env-configured directory, anchored to the repo when relative."""
    value = Path(os.environ.get(name, default))
    return value if value.is_absolute() else REPO_ROOT / value


STORAGE_ROOT = _configured_dir("FILE_STORAGE_DIR", "storage/patient_files")

DEID_PDF_DIR = _configured_dir("DEID_PDF_DIR", "storage/deidentified/pdf")
DEID_DICOM_DIR = _configured_dir("DEID_DICOM_DIR", "storage/deidentified/dicom")

DEID_WORD_DIR = _configured_dir("DEID_WORD_DIR", "storage/deidentified/word")

DEID_DIRS = {
    "pdf": DEID_PDF_DIR,
    "dcm": DEID_DICOM_DIR,
    "dicom": DEID_DICOM_DIR,
    "doc": DEID_WORD_DIR,
    "docx": DEID_WORD_DIR,
}


def deid_dir_for(extension: str) -> Path:
    """The final directory for a de-identified file of this format."""
    return DEID_DIRS.get((extension or "").lower().lstrip("."), DEID_PDF_DIR)


def _allowed_roots():
    """Every directory a stored path is permitted to live under."""
    return [
        root.resolve()
        for root in (STORAGE_ROOT, DEID_PDF_DIR, DEID_DICOM_DIR, DEID_WORD_DIR)
    ]

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


def _patient_document_target(
    patient_id: str, extension: str, received_at: datetime
) -> Path:
    """A free path under the patient naming scheme. Creates the folder."""
    directory = patient_dir(patient_id, received_at)
    directory.mkdir(parents=True, exist_ok=True)

    document_type = document_type_for(extension)

    for _ in range(_SERIAL_ATTEMPTS):
        serial = new_document_serial()
        target = directory / document_name(
            patient_id, document_type, serial, extension
        )
        if not target.exists():
            return target

    raise ValidationError("Could not allocate a unique document serial")


def write_patient_document(
    patient_id: str,
    extension: str,
    data: bytes,
    received_at: datetime,
) -> Path:
    """Store one upload under the patient naming scheme."""
    target = _patient_document_target(patient_id, extension, received_at)

    target.write_bytes(data)
    log.info(
        "file_stored",
        patient_id=patient_id,
        document_type=document_type_for(extension),
        path=str(target),
        bytes=len(data),
    )
    return target


def move_patient_document(
    patient_id: str,
    extension: str,
    source: Path,
    received_at: datetime,
) -> Path:
    """Same destination as write_patient_document, for bytes already on disk.

    Staging and storage share a filesystem, so this is a rename rather
    than a copy -- the whole reason a background batch can move a folder
    of scans without reading any of them back into memory.
    """
    target = _patient_document_target(patient_id, extension, received_at)

    shutil.move(str(source), str(target))
    log.info(
        "file_moved",
        patient_id=patient_id,
        document_type=document_type_for(extension),
        source=str(source),
        path=str(target),
    )
    return target


def _application_document_target(
    application_id: str, file_id: str, sanitized_name: str
) -> Path:
    directory = application_dir(application_id)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{file_id}_{sanitized_name}"


def write_file(
    application_id: str, file_id: str, sanitized_name: str, data: bytes
) -> Path:
    """Legacy layout, kept for uploads whose patient cannot be resolved."""
    target = _application_document_target(application_id, file_id, sanitized_name)

    target.write_bytes(data)
    log.info(
        "file_stored",
        application_id=application_id,
        file_id=file_id,
        path=str(target),
        bytes=len(data),
    )
    return target


def move_file(
    application_id: str, file_id: str, sanitized_name: str, source: Path
) -> Path:
    """write_file's destination, for bytes already staged on disk."""
    target = _application_document_target(application_id, file_id, sanitized_name)

    shutil.move(str(source), str(target))
    log.info(
        "file_moved",
        application_id=application_id,
        file_id=file_id,
        source=str(source),
        path=str(target),
    )
    return target


def resolve_stored_path(stored: str) -> Path:
    """Resolve a path read back from Hive, refusing anything outside the storage roots."""
    roots = _allowed_roots()

    raw = Path(stored)
    candidate = (raw if raw.is_absolute() else REPO_ROOT / raw).resolve()

    for root in roots:
        if candidate.is_relative_to(root):
            return candidate

    tail = Path(*raw.parts[-2:]) if len(raw.parts) >= 2 else None
    if tail is not None:
        for root in roots:
            rehomed = (root / tail).resolve()
            # Re-check: '..' in the stored value must not survive the join.
            if rehomed.is_relative_to(root) and rehomed.exists():
                log.info("file_path_rehomed", stored=stored, resolved=str(rehomed))
                return rehomed

    log.error(
        "file_path_outside_storage_root",
        path=stored,
        storage_roots=[str(r) for r in roots],
    )
    raise ValidationError("Stored file path is outside the storage root")


def file_deidentified_output(stored: str, extension: str) -> Path:
    """Move a de-identified file from staging to its configured location."""
    source = resolve_stored_path(stored)
    destination_dir = deid_dir_for(extension)
    destination = destination_dir / source.name

    if source.resolve() == destination.resolve():
        return destination

    destination_dir.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    shutil.move(str(source), str(destination))
    log.info("deid_output_filed", source=str(source), destination=str(destination))
    return destination


def delete_file(stored: str) -> None:
    """Best effort: a missing file must not block deleting its row."""
    try:
        resolve_stored_path(stored).unlink(missing_ok=True)
    except Exception as exc:  # pragma: no cover - cleanup is not critical
        log.warning("file_delete_failed", path=stored, error=str(exc))
