"""Filesystem storage for customer documents.

Hive holds the metadata; the bytes live here. The layout is
    <FILE_STORAGE_DIR>/<customer_id>/<file_id>_<sanitized_name>
so a file is locatable from its row, collisions are impossible (the id is
unique), and one customer's documents can be removed as a unit.
"""
import mimetypes
import os
import re
import unicodedata
from pathlib import Path

from app.errors import ValidationError
from app.logging_setup import get_logger

log = get_logger(__name__)

# Configuration, not an environment check: on Cloudera AI point this at a
# project or mounted path.
STORAGE_ROOT = Path(os.environ.get("FILE_STORAGE_DIR", "storage/customer_files"))

# Uploads arrive from a user-chosen folder, so names are arbitrary. Only
# these characters survive sanitisation.
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_NAME = 120


def sanitize_filename(name: str) -> str:
    """Make an arbitrary upload name safe to place on disk.

    Strips any directory component (a folder upload sends paths like
    'sub/dir/scan.pdf', and '../' must never be honoured), normalises
    unicode, and collapses everything else to a conservative charset.
    """
    # Take the last segment regardless of separator style, so neither
    # 'a/b.pdf' nor 'a\\b.pdf' can escape the target directory.
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


def customer_dir(customer_id: str) -> Path:
    return STORAGE_ROOT / customer_id


def write_file(customer_id: str, file_id: str, sanitized_name: str, data: bytes) -> Path:
    """Writes the bytes and returns the path recorded in Hive."""
    directory = customer_dir(customer_id)
    directory.mkdir(parents=True, exist_ok=True)

    target = directory / f"{file_id}_{sanitized_name}"
    target.write_bytes(data)
    log.info(
        "file_stored",
        customer_id=customer_id,
        file_id=file_id,
        path=str(target),
        bytes=len(data),
    )
    return target


def resolve_stored_path(stored: str) -> Path:
    """Resolve a path read back from Hive, refusing anything outside the
    storage root.

    The column is only ever written by write_file(), but a row is data
    like any other -- if it were ever tampered with, serving it must not
    turn into arbitrary file read.
    """
    root = STORAGE_ROOT.resolve()
    candidate = Path(stored).resolve()

    if not candidate.is_relative_to(root):
        log.error("file_path_outside_storage_root", path=stored)
        raise ValidationError("Stored file path is outside the storage root")

    return candidate


def delete_file(stored: str) -> None:
    """Best effort: a missing file must not block deleting its row."""
    try:
        resolve_stored_path(stored).unlink(missing_ok=True)
    except Exception as exc:  # pragma: no cover - cleanup is not critical
        log.warning("file_delete_failed", path=stored, error=str(exc))
