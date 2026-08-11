"""Write what we know about a document into the document itself.

The `file_metadata` table records what a file *arrived* carrying -- the
PDF info dict, the DICOM tags, the Word core properties. Facts this
system produces afterwards (that a file was de-identified, when, for
which patient) are not that, and putting them in the same blob made the
row a mixture of two different things: one read out of the file, one
written by us, indistinguishable once stored.

So they go where they belong -- inside the output file, in each format's
own metadata, where they travel with the document when it leaves here.

These facts are *added*. The pipeline has already de-identified the
document's own metadata in place -- `Author: <PATIENT>` rather than no
author -- and overwriting that would throw away the fact that a person
was named there. See OCR/deid/metadata.py.

Nothing in this module raises. A redaction that succeeded must not be
reported as failed because a metadata write did not land.
"""
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from app.logging_setup import get_logger
from app.schemas import METADATA_EXTENSIONS

log = get_logger(__name__)

METHOD = "Hive OCR/NER de-identification"

# DICOM LO (Long String) tops out at 64 characters per value.
DICOM_LO_MAX = 64


def generated_facts(
    patient_id: str = "",
    output_name: str = "",
    output_type: str = "",
    by: str = "",
) -> Dict[str, str]:
    """The facts this system produces about a de-identified document."""
    facts = {
        "deidentified": "yes",
        "deidentified_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "deidentified_method": METHOD,
    }
    if patient_id:
        facts["patient_id"] = patient_id
    if output_name:
        facts["deidentified_file_name"] = output_name
    if output_type:
        facts["deidentified_file_type"] = output_type
    if by:
        facts["deidentified_by"] = by
    return facts


def _as_pairs(values: Dict[str, str]) -> List[str]:
    return [f"{key}={value}" for key, value in values.items() if value]


def _appended(existing: Optional[str], addition: str) -> str:
    """Our facts after whatever was already there, not instead of it."""
    current = (existing or "").strip()
    if not current:
        return addition
    if addition in current:
        return current
    return f"{current}; {addition}"


def _embed_pdf(path: Path, values: Dict[str, str]) -> None:
    import fitz

    document = fitz.open(str(path))
    temporary = path.with_name(path.name + ".embedding")

    try:
        # Added to, not replaced. The pipeline has already de-identified
        # these fields in place, and a de-identified 'Author: <PATIENT>'
        # is worth more than no author at all -- it says a person was
        # named there. Overwriting it would throw that away.
        existing = dict(document.metadata or {})
        existing["keywords"] = _appended(
            existing.get("keywords"), "; ".join(_as_pairs(values))
        )
        document.set_metadata(existing)

        # XMP holds its own uncoordinated copy of the same fields, which
        # pymupdf cannot rewrite selectively.
        try:
            document.del_xml_metadata()
        except Exception:  # pragma: no cover - absent on some builds
            pass

        document.save(str(temporary), garbage=3, deflate=True)
    finally:
        document.close()

    temporary.replace(path)


def _embed_dicom(path: Path, values: Dict[str, str]) -> None:
    import pydicom

    dataset = pydicom.dcmread(str(path), force=True)

    dataset.PatientIdentityRemoved = "YES"

    # DeidentificationMethod is LO with VM 1-n: a list of short strings,
    # which is exactly the shape these facts have. The pipeline may have
    # written its own entry already -- keep it and add to it.
    existing = dataset.get("DeidentificationMethod") or []
    if isinstance(existing, str):
        existing = [existing]

    entries = [str(item) for item in existing]
    for pair in _as_pairs(values):
        if len(pair) <= DICOM_LO_MAX and pair not in entries:
            entries.append(pair)

    dataset.DeidentificationMethod = entries
    dataset.save_as(str(path))


def _embed_word(path: Path, values: Dict[str, str]) -> None:
    import docx

    document = docx.Document(str(path))
    properties = document.core_properties

    # Added to, not replaced -- the pipeline has already de-identified
    # these in place. See _embed_pdf.
    properties.comments = _appended(
        properties.comments, "; ".join(_as_pairs(values))
    )

    document.save(str(path))


_EMBEDDERS = {
    "pdf": _embed_pdf,
    "dicom": _embed_dicom,
    "word": _embed_word,
}


def embed_metadata(
    path: Path, extension: str, values: Dict[str, str]
) -> Optional[str]:
    """Write `values` into the file's own metadata.

    Returns the format written, or None when nothing was (unsupported
    format, or the write failed -- both are logged, neither raises).
    """
    if not values:
        return None

    file_type = METADATA_EXTENSIONS.get((extension or "").lower().lstrip("."))
    if file_type is None:
        log.info(
            "embed_metadata_unsupported", path=str(path), extension=extension
        )
        return None

    if not path.is_file():
        log.warning("embed_metadata_missing_file", path=str(path))
        return None

    try:
        _EMBEDDERS[file_type](path, values)
    except Exception as exc:
        log.error(
            "embed_metadata_failed",
            path=str(path),
            file_type=file_type,
            error=str(exc)[:300],
        )
        return None

    log.info(
        "embed_metadata_written",
        path=str(path),
        file_type=file_type,
        fields=len(values),
    )
    return file_type
