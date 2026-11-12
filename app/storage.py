import mimetypes
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app import blobstore
from app.blobstore import StoragePath
from app.errors import ValidationError
from app.ids import new_document_serial
from app.logging_setup import get_logger, ref
from app.schemas import METADATA_EXTENSIONS

log = get_logger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _legacy_key(stored: str) -> Optional[str]:
    """Paths written before Ozone ('/home/cdsw/storage/patient_files/x.pdf' or
    'storage/patient_files/x.pdf'): the part after the 'storage' folder."""
    parts = Path(stored).parts
    if "storage" in parts:
        index = len(parts) - 1 - list(reversed(parts)).index("storage")
        rest = parts[index + 1:]
        return "/".join(rest) if rest else None
    return None


def _configured_dir(name: str, default: str) -> StoragePath:
    """A folder inside STORAGE_ROOT (local folder or Ozone). Settings keep their
    old form: "storage/patient_files" means the folder "patient_files" in the root.
    An absolute path is accepted only if it lies inside a local STORAGE_ROOT."""
    raw = (os.environ.get(name) or default).strip().replace("\\", "/")
    if Path(raw).is_absolute():
        store = blobstore.get_store()
        base = getattr(store, "base", None)
        if isinstance(base, Path) and Path(raw).resolve().is_relative_to(base):
            return StoragePath(Path(raw).resolve().relative_to(base).as_posix())
        # An old absolute setting such as /home/cdsw/storage/patient_files:
        # use the part after "storage" as the folder inside STORAGE_ROOT.
        legacy = _legacy_key(raw)
        if legacy:
            log.warning("storage_setting_rehomed", setting=name, folder=legacy, root=store.root)
            return StoragePath(legacy)
        raise ValidationError(f"{name}={raw} must be a folder inside STORAGE_ROOT ({store.root})")
    raw = raw.removeprefix("./")
    if raw == "storage" or raw.startswith("storage/"):
        raw = raw[len("storage"):].lstrip("/")
    return StoragePath(raw)


def _local_dir(name: str, default: str) -> Path:
    """Small bookkeeping folders that stay on the project disk (worker locks,
    heartbeats, progress): no documents, rewritten every few seconds."""
    value = Path(os.environ.get(name, default))
    return value if value.is_absolute() else REPO_ROOT / value


def _store_or_local_dir(name: str, default: str):
    """Folders people open directly (abstraction folders, project workspaces)
    are in the store by default; an absolute path outside a local STORAGE_ROOT
    puts them on the project disk instead (Ozone cannot be browsed by people)."""
    raw = (os.environ.get(name) or "").strip()
    if raw and Path(raw).is_absolute():
        store = blobstore.get_store()
        base = getattr(store, "base", None)
        if not (isinstance(base, Path) and Path(raw).resolve().is_relative_to(base)):
            return Path(raw)
    return _configured_dir(name, default)


def state_root() -> Path:
    return _local_dir("HIVE_STATE_DIR", "state")


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


def deid_dir_for(extension: str) -> StoragePath:
    return DEID_DIRS.get((extension or "").lower().lstrip("."), DEID_PDF_DIR)


def intake_root() -> StoragePath:
    return _configured_dir("INTAKE_DIR", "storage/incoming_data")


def submitted_root() -> StoragePath:
    return _configured_dir("SUBMITTED_DIR", "storage/submitted")


def data_root() -> StoragePath:
    return _configured_dir("DATA_DIR", "storage/pending_data")


def submitted_data_root() -> StoragePath:
    return _configured_dir("SUBMITTED_DATA_DIR", "storage/submitted_data")


def projects_root():
    return _store_or_local_dir("PROJECTS_DIR", "storage/projects")


def zone2_inbox_root() -> StoragePath:
    return _configured_dir("ZONE2_INBOX_DIR", "storage/zone2_inbox")


def zone2_root() -> StoragePath:
    return _configured_dir("ZONE2_DIR", "storage/zone2")


def abstraction_root():
    return _store_or_local_dir("ABSTRACTION_DIR", "storage/abstraction")


def submitted_dir_for(patient_id: str) -> StoragePath:
    return submitted_root() / safe_path_segment(patient_id)


def _allowed_roots():
    return [
        root
        for root in (
            STORAGE_ROOT,
            DEID_PDF_DIR,
            DEID_DICOM_DIR,
            DEID_WORD_DIR,
            intake_root(),
            submitted_root(),
            data_root(),
            submitted_data_root(),
            abstraction_root(),
            projects_root(),
            zone2_inbox_root(),
            zone2_root(),
        )
    ]


def move_into(source: StoragePath, directory: StoragePath) -> StoragePath:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / source.name

    if target.exists() and target != source:
        for n in range(2, 10_000):
            candidate = directory / f"{source.stem}_{n}{source.suffix}"
            if not candidate.exists():
                target = candidate
                break
        else:
            raise ValidationError(f"No free name for {source.name} in {directory}")

    if target != source:
        blobstore.move(source, target)
        log.info("file_moved", source_ref=ref(source), file_ref=ref(target))
    return target

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_NAME = 120


def sanitize_filename(name: str) -> str:
    base = re.split(r"[\\/]", name)[-1].strip()

    normalized = unicodedata.normalize("NFKD", base)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    cleaned = _UNSAFE.sub("_", ascii_only).strip("._-")

    if not cleaned:
        cleaned = "file"

    stem, dot, suffix = cleaned.rpartition(".")
    if dot:
        stem = stem[: _MAX_NAME - len(suffix) - 1] or "file"
        return f"{stem}.{suffix}"
    return cleaned[:_MAX_NAME]


def file_extension(name: str) -> str:
    suffix = Path(name).suffix
    return suffix[1:].lower() if suffix else ""


def guess_mime_type(name: str, provided: str | None) -> str:
    if provided and provided != "application/octet-stream":
        return provided
    guessed, _ = mimetypes.guess_type(name)
    return guessed or "application/octet-stream"


def application_dir(application_id: str) -> StoragePath:
    return STORAGE_ROOT / application_id


RECEIVED_FORMAT = "%Y%m%dT%H%M%SZ"

_SERIAL_ATTEMPTS = 5


def patient_dir(patient_id: str, received_at: datetime) -> StoragePath:
    return STORAGE_ROOT / f"{patient_id}-{received_at.strftime(RECEIVED_FORMAT)}"


def safe_path_segment(value: str) -> str:
    cleaned = _UNSAFE.sub("_", (value or "").strip()).strip("._-")
    return cleaned[:_MAX_NAME] or "unknown"


def document_type_for(extension: str) -> str:
    known = METADATA_EXTENSIONS.get((extension or "").lower().lstrip("."))
    if known:
        return known

    fallback = _UNSAFE.sub("", (extension or "").lower())
    return fallback or "file"


DATE_FORMAT = "%Y%m%d"


def document_name(
    patient_id: str,
    document_type: str,
    serial: str,
    extension: str,
    received_at: Optional[datetime] = None,
) -> str:
    suffix = f".{extension.lower()}" if extension else ""
    day = (received_at or datetime.now(timezone.utc)).strftime(DATE_FORMAT)
    return f"{patient_id}-{document_type}-{day}-{serial}{suffix}"


def _patient_document_target(
    patient_id: str, extension: str, received_at: datetime
) -> StoragePath:
    directory = patient_dir(patient_id, received_at)
    directory.mkdir(parents=True, exist_ok=True)

    document_type = document_type_for(extension)

    for _ in range(_SERIAL_ATTEMPTS):
        serial = new_document_serial()
        target = directory / document_name(
            patient_id, document_type, serial, extension, received_at
        )
        if not target.exists():
            return target

    raise ValidationError("Could not allocate a unique document serial")


def write_patient_document(
    patient_id: str,
    extension: str,
    data: bytes,
    received_at: datetime,
) -> StoragePath:
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
    source,
    received_at: datetime,
) -> StoragePath:
    """source: a stored file, or a local temporary file (it is uploaded and removed)."""
    target = _patient_document_target(patient_id, extension, received_at)

    blobstore.move(source, target)
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
) -> StoragePath:
    directory = application_dir(application_id)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{file_id}_{sanitized_name}"


def write_file(
    application_id: str, file_id: str, sanitized_name: str, data: bytes
) -> StoragePath:
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
    application_id: str, file_id: str, sanitized_name: str, source
) -> StoragePath:
    target = _application_document_target(application_id, file_id, sanitized_name)

    blobstore.move(source, target)
    log.info(
        "file_moved",
        application_id=application_id,
        file_id=file_id,
        source=str(source),
        path=str(target),
    )
    return target


def stored_name(path: StoragePath) -> str:
    """What goes in the database and in sidecar files for a stored file."""
    return str(path)


def resolve_stored_path(stored) -> StoragePath:
    """A path from the database or a sidecar -> StoragePath inside an allowed folder."""
    if isinstance(stored, StoragePath):
        candidate = stored
    elif isinstance(stored, str) and stored.startswith(blobstore.STORED_PREFIX):
        candidate = blobstore.stored_path(stored)
    else:
        key = _legacy_key(str(stored or ""))
        candidate = StoragePath(key) if key else None
    roots = _allowed_roots()

    if candidate is not None and any(candidate.is_relative_to(root) for root in roots):
        return candidate

    raw = Path(str(stored or ""))
    tail = "/".join(raw.parts[-2:]) if len(raw.parts) >= 2 else None
    if tail and ".." not in raw.parts[-2:]:
        for root in roots:
            rehomed = root / tail
            if rehomed.exists():
                log.info("file_path_rehomed", file_ref=ref(stored))
                return rehomed

    log.error(
        "file_path_outside_storage_root",
        file_ref=ref(stored),
        storage_roots=[str(r) for r in roots],
    )
    from app.access_log import FAILURE, INTEGRITY, record_access

    record_access(
        INTEGRITY,
        outcome=FAILURE,
        resource_type="file_path",
        detail=f"outside storage root: {stored}"[:500],
    )
    raise ValidationError("Stored file path is outside the storage root")


def file_deidentified_output(
    stored: str, extension: str, patient_id: str = ""
) -> StoragePath:
    source = resolve_stored_path(stored)

    destination_dir = deid_dir_for(extension)
    if patient_id:
        destination_dir = destination_dir / safe_path_segment(patient_id)

    destination = destination_dir / source.name

    if source == destination:
        return destination

    destination_dir.mkdir(parents=True, exist_ok=True)
    blobstore.move(source, destination)
    log.info("deid_output_filed", source_ref=ref(source), file_ref=ref(destination))
    return destination


def delete_file(stored: str) -> None:
    try:
        resolve_stored_path(stored).unlink(missing_ok=True)
    except Exception as exc:
        log.warning("file_delete_failed", file_ref=ref(stored), error=str(exc))


def prune_empty_dirs(directory) -> int:
    """Remove `directory` and its parents while they are empty, stopping at the
    storage folders themselves."""
    if not isinstance(directory, StoragePath):
        return 0
    roots = _allowed_roots()
    removed = 0
    current = directory

    while any(current.is_relative_to(root) and current != root for root in roots):
        try:
            current.rmdir()
        except OSError:
            break

        log.info("empty_dir_removed", directory=str(current))
        removed += 1
        current = current.parent

    return removed


def prune_stored_folders(*stored: Optional[str]) -> None:
    for path in stored:
        if not path:
            continue
        try:
            prune_empty_dirs(resolve_stored_path(path).parent)
        except Exception:
            continue
