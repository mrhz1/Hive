from pathlib import Path
from typing import Optional

from app.logging_setup import get_logger
from app.schemas import METADATA_EXTENSIONS

log = get_logger(__name__)

DICOM_PREAMBLE_BYTES = 128
DICOM_MAGIC = b"DICM"

PDF_MAGIC = b"%PDF-"

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

ZIP_MAGIC = b"PK\x03\x04"

SNIFF_BYTES = 4096

KNOWN_EXTENSIONS = frozenset(METADATA_EXTENSIONS)


def name_extension(name: str) -> str:
    suffix = Path(name).suffix
    return suffix[1:].lower() if suffix else ""


def sniff_extension(head: bytes) -> Optional[str]:
    if not head:
        return None

    if (
        len(head) >= DICOM_PREAMBLE_BYTES + len(DICOM_MAGIC)
        and head[DICOM_PREAMBLE_BYTES : DICOM_PREAMBLE_BYTES + len(DICOM_MAGIC)]
        == DICOM_MAGIC
    ):
        return "dcm"

    if head.startswith(DICOM_MAGIC):
        return "dcm"

    if head.startswith(PDF_MAGIC):
        return "pdf"

    if head.startswith(OLE_MAGIC):
        return "doc"

    if head.startswith(ZIP_MAGIC) and b"word/" in head:
        return "docx"

    return None


def resolve_extension(name: str, head: bytes) -> str:
    named = name_extension(name)
    if named in KNOWN_EXTENSIONS:
        return named

    sniffed = sniff_extension(head)
    if sniffed is None:
        return named

    log.info(
        "file_type_sniffed", name=name, named_extension=named or "(none)",
        detected=sniffed,
    )
    return sniffed


def head_of(path) -> bytes:
    try:
        with open(path, "rb") as handle:
            return handle.read(SNIFF_BYTES)
    except OSError as exc:
        log.warning("file_head_unreadable", path=str(path), error=str(exc))
        return b""
