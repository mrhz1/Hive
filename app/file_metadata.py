"""Extract metadata from an uploaded document.

Called once per file at upload time (app/routers/patient_application_files
.py), and its output is stored as a JSON string in `file_metadata`.

Three formats are read: **PDF, DICOM and Word**. Anything else is
recorded `unsupported` rather than skipped, so a row always exists and
the UI can say "no metadata for this format" instead of showing an empty
object as though the file had none.

## Two rules this module is built around

**Extraction must never fail an upload.** The bytes are already on disk
and the row already exists by the time this runs; a malformed PDF is a
missing metadata row, not a lost document. Every extractor is wrapped, and
the failure is recorded on the row with its reason.

**Metadata is PHI.** DICOM headers carry PatientName, PatientID and
birth date; PDF /Author is routinely a clinician. So values are never
logged, and DICOM pixel data is never read (`stop_before_pixels`) -- it is
both large and the most sensitive part of the file.

The parsers are imported lazily and their absence is reported as a failed
extraction rather than an ImportError at startup: the API must keep
serving if an optional dependency did not install.
"""
import datetime as _datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from app.logging_setup import get_logger
from app.schemas import METADATA_EXTENSIONS

log = get_logger(__name__)

# A cap on what goes into Hive. Some DICOM headers carry hundreds of
# private tags and some PDFs embed an entire XMP document; a metadata
# blob larger than the row it describes helps nobody.
MAX_VALUE_CHARS = 2000
MAX_FIELDS = 200


def file_type_for(extension: str) -> Optional[str]:
    """'pdf' / 'dicom' / 'word', or None when we do not read this format."""
    return METADATA_EXTENSIONS.get((extension or "").lower().lstrip("."))


def _clean(value: Any) -> Optional[str]:
    """Normalise one attribute to a short string, or None to drop it.

    Everything becomes a string deliberately: these headers are wildly
    inconsistent across producers (a DICOM date is a string, a PDF date is
    a string in a different format, python-docx hands back a datetime),
    and a consumer that has to handle three types per field handles none
    of them.
    """
    if value is None:
        return None
    if isinstance(value, (_datetime.datetime, _datetime.date)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        # Binary attributes are rarely meaningful and never displayable.
        return None

    text = str(value).strip()
    if not text:
        return None
    return text[:MAX_VALUE_CHARS]


def _collect(pairs) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for name, value in pairs:
        if len(out) >= MAX_FIELDS:
            break
        cleaned = _clean(value)
        if cleaned is not None:
            out[name] = cleaned
    return out


def _extract_pdf(path: Path) -> Dict[str, str]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    info = reader.metadata or {}

    fields = [("page_count", len(reader.pages)), ("encrypted", reader.is_encrypted)]
    # /Title, /Author, ... -> title, author. The leading slash is a PDF
    # dictionary-key artefact, not part of the name.
    fields.extend((str(key).lstrip("/").lower(), value) for key, value in info.items())
    return _collect(fields)


def _extract_dicom(path: Path) -> Dict[str, str]:
    import pydicom

    # stop_before_pixels: the header is the metadata, and the pixel data
    # is both the bulk of the file and the part we least want in memory.
    dataset = pydicom.dcmread(str(path), stop_before_pixels=True, force=True)

    def pairs():
        for element in dataset:
            # Skip the raw pixel element if force=True let it through, and
            # sequences, which are nested datasets rather than values.
            if element.tag == 0x7FE00010 or element.VR == "SQ":
                continue
            keyword = element.keyword or str(element.tag)
            yield keyword, element.value

    return _collect(pairs())


def _extract_word(path: Path) -> Dict[str, str]:
    import docx

    document = docx.Document(str(path))
    core = document.core_properties

    return _collect(
        [
            ("title", core.title),
            ("author", core.author),
            ("subject", core.subject),
            ("keywords", core.keywords),
            ("category", core.category),
            ("comments", core.comments),
            ("last_modified_by", core.last_modified_by),
            ("revision", core.revision),
            ("created", core.created),
            ("modified", core.modified),
            ("paragraph_count", len(document.paragraphs)),
            ("table_count", len(document.tables)),
        ]
    )


_EXTRACTORS = {
    "pdf": _extract_pdf,
    "dicom": _extract_dicom,
    "word": _extract_word,
}


def extract(path: Path, extension: str) -> Tuple[str, Dict[str, str], str, Optional[str]]:
    """Read one file's metadata.

    Returns (file_type, metadata, status, error) ready for
    FileMetadataCreate. Never raises -- see the module docstring.
    """
    file_type = file_type_for(extension)
    if file_type is None:
        return (extension or "unknown").lower(), {}, "unsupported", None

    try:
        metadata = _EXTRACTORS[file_type](path)
    except ImportError as exc:
        # An optional dependency is missing. Worth saying plainly, because
        # every file of this type will fail the same way until it is
        # installed, and the reason is not in the file.
        log.error("file_metadata_parser_missing", file_type=file_type, error=str(exc))
        return file_type, {}, "failed", f"Parser not installed: {exc}"
    except Exception as exc:
        # The document is malformed, encrypted, or not what its extension
        # claims. The message is safe to keep (it describes the parse, not
        # the content); the values are not, so nothing else is logged.
        log.warning(
            "file_metadata_extraction_failed",
            file_type=file_type,
            error=str(exc)[:200],
        )
        return file_type, {}, "failed", str(exc)[:500]

    log.info("file_metadata_extracted", file_type=file_type, fields=len(metadata))
    return file_type, metadata, "ok", None
