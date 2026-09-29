from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from app.logging_setup import get_logger
from app.schemas import METADATA_EXTENSIONS

log = get_logger(__name__)

METHOD = "Hive OCR/NER de-identification"

DICOM_LO_MAX = 64


def generated_facts(
    patient_id: str = "",
    output_name: str = "",
    output_type: str = "",
    by: str = "",
    source_name: str = "",
) -> Dict[str, str]:
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
    if source_name:
        facts["deidentified_from"] = source_name
    return facts


def _to_pairs(values: Dict[str, str]) -> List[str]:
    pairs = []
    for key, value in values.items():
        if value:
            pairs.append(f"{key}={value}")
    return pairs


def _append_text(existing: Optional[str], addition: str) -> str:
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
        existing = dict(document.metadata or {})
        existing["keywords"] = _append_text(
            existing.get("keywords"), "; ".join(_to_pairs(values))
        )
        document.set_metadata(existing)

        try:
            document.del_xml_metadata()
        except Exception:
            pass

        document.save(str(temporary), garbage=3, deflate=True)
    finally:
        document.close()

    temporary.replace(path)


def _embed_dicom(path: Path, values: Dict[str, str]) -> None:
    import pydicom

    dataset = pydicom.dcmread(str(path), force=True)

    dataset.PatientIdentityRemoved = "YES"

    existing = dataset.get("DeidentificationMethod") or []
    if isinstance(existing, str):
        existing = [existing]

    entries = [str(item) for item in existing]
    for pair in _to_pairs(values):
        if len(pair) <= DICOM_LO_MAX and pair not in entries:
            entries.append(pair)

    dataset.DeidentificationMethod = entries
    dataset.save_as(str(path))


def _embed_word(path: Path, values: Dict[str, str]) -> None:
    import docx

    document = docx.Document(str(path))
    properties = document.core_properties

    properties.comments = _append_text(
        properties.comments, "; ".join(_to_pairs(values))
    )

    document.save(str(path))


def embed_metadata(
    path: Path, extension: str, values: Dict[str, str]
) -> Optional[str]:
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
        if file_type == "pdf":
            _embed_pdf(path, values)
        elif file_type == "dicom":
            _embed_dicom(path, values)
        elif file_type == "word":
            _embed_word(path, values)
    except Exception as e:
        log.error(
            "embed_metadata_failed",
            path=str(path),
            file_type=file_type,
            error=str(e)[:300],
        )
        return None

    log.info(
        "embed_metadata_written",
        path=str(path),
        file_type=file_type,
        fields=len(values),
    )
    return file_type
