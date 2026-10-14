import io
import json
import os
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

UNKNOWN = "UNKNOWN"

AUTOMATIC = "R"
MANUAL = "RR"

DICOM_MODALITIES = frozenset("""
    AR ASMT AU BDUS BI BMD CR CT CTPROTOCOL DG DOC DX ECG EEG EMG EOG EPS ES
    FID GM HC HD IO IOL IVOCT IVUS KER KO LEN LS M3D MG MR NM OAM OCT OP OPM
    OPT OPTBSV OPTENF OPV OSS OT PLAN POS PR PT PX REG RESP RF RG RTDOSE
    RTIMAGE RTINTENT RTPLAN RTRAD RTRECORD RTSEGANN RTSTRUCT RWV SEG SM SMR SR
    SRF STAIN TEXTUREMAP TG US VA XA XAPROTOCOL XC
""".split())

NAME_MODALITIES = frozenset("""
    BDUS BMD CR CT DX ECG EEG EMG EPS IVOCT IVUS MG MR NM OCT PT PX RF RG US
    XA XC
""".split())

ALIASES = {
    "MRI": "MR",
    "MRA": "MR",
    "FMRI": "MR",
    "CTA": "CT",
    "PET": "PT",
    "SPECT": "NM",
    "ECHO": "US",
    "ULTRASOUND": "US",
    "SONO": "US",
    "XRAY": "DX",
    "XR": "DX",
    "RADIOGRAPH": "DX",
    "ANGIO": "XA",
    "MAMMO": "MG",
    "MAMMOGRAM": "MG",
    "FLUORO": "RF",
    "EKG": "ECG",
    "DEXA": "BMD",
    "DXA": "BMD",
}

DOCUMENT_TYPES = (
    "ENROLLMENT", "CONTACT", "CONSENT", "OPERATIVE", "DISCHARGE",
    "ECHO_REPORT", "ANGIO_REPORT", "MRI_REPORT", "ECG_REPORT",
    "IMAGE", "STS_EXTRACT", "OTHER",
)

TYPE_KEYWORDS: List[Tuple[str, Tuple[str, ...]]] = [
    ("CONSENT", ("consent", "consent form", "assent")),
    ("CONTACT", ("contact form", "contact information", "contact info",
                 "change of contact", "contact update", "contact")),
    ("ENROLLMENT", ("enrollment", "enrolment", "enroll", "enrol", "registration form")),
    ("OPERATIVE", ("operative", "op note", "op report", "operation", "surgical report",
                   "surgery report", "operative report")),
    ("DISCHARGE", ("discharge", "discharge summary", "dc summary", "d c summary")),
    ("ECHO_REPORT", ("echo", "echocardiogram", "echocardiography", "tte", "tee")),
    ("ANGIO_REPORT", ("angio", "angiogram", "angiography", "cath", "catheterization",
                      "catheterisation")),
    ("MRI_REPORT", ("mri", "cmr", "cardiac mri", "magnetic resonance")),
    ("ECG_REPORT", ("ecg", "ekg", "electrocardiogram", "electrocardiography")),
]

IMAGE_EXTENSIONS = ("jpg", "jpeg", "png", "tif", "tiff", "bmp", "gif")
SPREADSHEET_EXTENSIONS = ("xlsx", "xls", "csv")

DICOM_DATE_TAGS = ("StudyDate", "SeriesDate", "AcquisitionDate", "ContentDate")

_DATE = re.compile(
    r"(?<!\d)((?:19|20)\d{2})[-_. ]?(0[1-9]|1[0-2])[-_. ]?(0[1-9]|[12]\d|3[01])(?!\d)"
)
_X_RAY = re.compile(r"X[-_ ]RAY", re.IGNORECASE)
_WORD = re.compile(r"[A-Za-z]+")

_NAME = re.compile(
    r"^(?P<code>[A-Z0-9]+)_(?:(?P<modality>[A-Z0-9]+(?:_[A-Z0-9]+)*?)_)?"
    r"(?P<day>\d{8}|UNKNOWN)_(?P<serial>\d{16})"
    r"(?:_(?P<redaction>RR?))?(?P<extension>\..*)?$"
)


@dataclass(frozen=True)
class DocumentInfo:
    modality: str = UNKNOWN
    date: str = UNKNOWN

    def stem(self, code: str, serial: str, redaction: Optional[str] = AUTOMATIC) -> str:
        stem = f"{code or 'unknown'}_{self.modality}_{self.date}_{serial}"
        return f"{stem}_{redaction}" if redaction else stem


def clean_type(value: Optional[str]) -> Optional[str]:
    word = re.sub(r"[\s\-]+", "_", (value or "").strip().upper())
    return word if word in DOCUMENT_TYPES else None


def clean_modality(value: Optional[str]) -> Optional[str]:
    typed = clean_type(value)
    if typed:
        return typed
    word = (value or "").strip().upper().replace("-", "").replace(" ", "")
    if word == UNKNOWN:
        return UNKNOWN
    word = ALIASES.get(word, word)
    return word if word in DICOM_MODALITIES else None


def clean_date(value: Optional[str]) -> Optional[str]:
    text = (value or "").strip()
    if text.upper() == UNKNOWN:
        return UNKNOWN
    match = _DATE.fullmatch(text)
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    try:
        return date(year, month, day).strftime("%Y%m%d")
    except ValueError:
        return None


def _without_code(name: str, code: str) -> str:
    stem = Path(name).stem
    if code:
        stem = re.sub(re.escape(code), " ", stem, flags=re.IGNORECASE)
    return stem


def modality_from_name(name: str, code: str = "") -> str:
    text = _X_RAY.sub(" XRAY ", _without_code(name, code))
    for word in _WORD.findall(text):
        word = word.upper()
        modality = ALIASES.get(word, word)
        if modality in NAME_MODALITIES:
            return modality
    return UNKNOWN


def _keywords() -> List[Tuple[str, Tuple[str, ...]]]:
    path = os.environ.get("DOCUMENT_TYPES_FILE")
    if not path:
        return TYPE_KEYWORDS
    try:
        extra: Dict[str, List[str]] = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return TYPE_KEYWORDS
    merged = [(kind, words + tuple(extra.get(kind, ()))) for kind, words in TYPE_KEYWORDS]
    known = {kind for kind, _ in TYPE_KEYWORDS}
    merged += [
        (kind, tuple(words)) for kind, words in extra.items()
        if kind in DOCUMENT_TYPES and kind not in known
    ]
    return merged


def type_from_name(name: str, extension: str = "", code: str = "") -> str:
    extension = (extension or Path(name).suffix).lower().lstrip(".")
    if extension in IMAGE_EXTENSIONS:
        return "IMAGE"
    text = " " + " ".join(re.split(r"[^a-z0-9]+", _without_code(name, code).lower())) + " "
    if extension in SPREADSHEET_EXTENSIONS and " sts " in text:
        return "STS_EXTRACT"
    for kind, words in _keywords():
        if any(f" {' '.join(word.lower().split())} " in text for word in words):
            return kind
    return UNKNOWN


def date_from_name(name: str, code: str = "") -> str:
    for match in _DATE.finditer(_without_code(name, code)):
        found = clean_date("".join(match.groups()))
        if found:
            return found
    return UNKNOWN


def from_dicom(source: Union[Path, bytes]) -> DocumentInfo:
    import pydicom

    try:
        handle = io.BytesIO(source) if isinstance(source, bytes) else str(source)
        dataset = pydicom.dcmread(handle, stop_before_pixels=True, force=True)
    except Exception:
        return DocumentInfo()

    modality = clean_modality(str(dataset.get("Modality", "") or "")) or UNKNOWN

    found = UNKNOWN
    for tag in DICOM_DATE_TAGS:
        found = clean_date(str(dataset.get(tag, "") or "")[:8]) or UNKNOWN
        if found != UNKNOWN:
            break

    return DocumentInfo(modality=modality, date=found)


def is_dicom_extension(extension: str) -> bool:
    return (extension or "").lower().lstrip(".") in ("dcm", "dicom")


def find(
    name: str,
    extension: str,
    code: str = "",
    source: Union[Path, bytes, None] = None,
) -> DocumentInfo:
    day = date_from_name(name, code)
    if (extension or "").lower().lstrip(".") in IMAGE_EXTENSIONS:
        return DocumentInfo(modality=modality_from_name(name, code), date=day)
    if not is_dicom_extension(extension):
        kind = type_from_name(name, extension, code)
        if kind == UNKNOWN:
            kind = modality_from_name(name, code)
        return DocumentInfo(modality=kind, date=day)

    from_name = DocumentInfo(modality=modality_from_name(name, code), date=day)
    if source is None:
        return from_name

    tags = from_dicom(source)
    return DocumentInfo(
        modality=tags.modality if tags.modality != UNKNOWN else from_name.modality,
        date=tags.date if tags.date != UNKNOWN else from_name.date,
    )


def parse_name(name: str) -> Optional[dict]:
    match = _NAME.match(name)
    return match.groupdict() if match else None


def renamed(
    name: str, info: Optional[DocumentInfo] = None, redaction: Optional[str] = None
) -> Optional[str]:
    parts = parse_name(name)
    if parts is None:
        return None
    if info is None and parts["modality"]:
        info = DocumentInfo(modality=parts["modality"], date=parts["day"])
    elif info is None:
        info = DocumentInfo()
    return info.stem(
        parts["code"], parts["serial"], redaction or parts["redaction"]
    ) + (parts["extension"] or "")


def rename(path: Path, info: DocumentInfo) -> Path:
    new_name = renamed(path.name, info)
    if new_name is None:
        raise ValueError(f"'{path.name}' is not a redacted file name")
    if new_name == path.name:
        return path

    target = path.with_name(new_name)
    if target.exists():
        raise FileExistsError(f"'{new_name}' already exists")

    old_stem, new_stem = path.stem, target.stem
    path.rename(target)
    for other in sorted(path.parent.iterdir()):
        if other.is_file() and other.name.startswith(old_stem + "."):
            other.rename(other.with_name(new_stem + other.name[len(old_stem):]))
    return target
