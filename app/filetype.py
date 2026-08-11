"""What an uploaded file actually is, when its name does not say.

PACS exports routinely have no extension at all -- `IM000001`, or a bare
SOP instance UID -- and a name is only ever a claim about content in any
case. Everything downstream keys off the extension: whether the file can
be de-identified, whether its metadata is read, and which `DEID_*_DIR` its
redacted copy is filed under. A DICOM landing as '' was therefore
un-de-identifiable, unread, and would have been filed with the PDFs.

So the extension is resolved from the bytes when the name does not
already name a format we handle. The name still wins when it does: it
carries the distinction between `.doc` and `.docx`, and between `.dcm`
and `.dicom`, that the magic numbers alone cannot.
"""
from pathlib import Path
from typing import Optional

from app.logging_setup import get_logger
from app.schemas import METADATA_EXTENSIONS

log = get_logger(__name__)

# DICOM Part 10: a 128-byte preamble, then 'DICM'.
DICOM_PREAMBLE_BYTES = 128
DICOM_MAGIC = b"DICM"

PDF_MAGIC = b"%PDF-"

# OLE2 compound file -- legacy .doc (and .xls, .ppt: see _sniff).
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

ZIP_MAGIC = b"PK\x03\x04"

# Enough for the DICOM preamble plus a look at a zip's first entries.
SNIFF_BYTES = 4096

# The formats a name may authoritatively claim; anything else gets sniffed.
KNOWN_EXTENSIONS = frozenset(METADATA_EXTENSIONS)


def name_extension(name: str) -> str:
    """Lowercased extension without the dot, '' when there is none."""
    suffix = Path(name).suffix
    return suffix[1:].lower() if suffix else ""


def sniff_extension(head: bytes) -> Optional[str]:
    """The format these opening bytes belong to, or None if unrecognised."""
    if not head:
        return None

    if (
        len(head) >= DICOM_PREAMBLE_BYTES + len(DICOM_MAGIC)
        and head[DICOM_PREAMBLE_BYTES : DICOM_PREAMBLE_BYTES + len(DICOM_MAGIC)]
        == DICOM_MAGIC
    ):
        return "dcm"

    # Some writers drop the preamble and start straight at the magic.
    if head.startswith(DICOM_MAGIC):
        return "dcm"

    if head.startswith(PDF_MAGIC):
        return "pdf"

    if head.startswith(OLE_MAGIC):
        # Every legacy Office format shares this container. Word is the
        # only one this application handles, and calling a stray .xls a
        # .doc merely fails later in the same way it would anyway.
        return "doc"

    # OOXML is a zip; the entry names are visible in the raw stream, and
    # 'word/' is what separates a .docx from an .xlsx or a plain archive.
    if head.startswith(ZIP_MAGIC) and b"word/" in head:
        return "docx"

    return None


def resolve_extension(name: str, head: bytes) -> str:
    """The extension to file this upload under.

    A name that already claims a format we handle is trusted. Otherwise
    the bytes decide, and if they say nothing either the name's extension
    is kept as-is -- an unknown format should stay unknown rather than be
    guessed into the wrong pipeline.
    """
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
    """The opening bytes of a file already on disk."""
    try:
        with open(path, "rb") as handle:
            return handle.read(SNIFF_BYTES)
    except OSError as exc:
        log.warning("file_head_unreadable", path=str(path), error=str(exc))
        return b""
