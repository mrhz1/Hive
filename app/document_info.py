"""The modality and date a redacted file is named by.

A redacted file is named `<code>_<modality>_<date>_<16-digit serial>.<ext>`,
e.g. `AA1234_MR_20190312_1790261077741000.pdf`.

- DICOM: the Modality tag, and the first of StudyDate, SeriesDate,
  AcquisitionDate, ContentDate.
- PDF and Word: from the file name the site gave it, e.g.
  `AA1234_MRI_2019-03-12.pdf`. The modality is a whole word of the name
  (`MRI`, `CT`, ...), the date is `YYYYMMDD` or `YYYY-MM-DD` (also with `_`,
  `.` or a space).

Anything not found is `UNKNOWN`, and staff set it on the review screen
(`rename`).
"""

import io
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional, Union

UNKNOWN = "UNKNOWN"

# DICOM modality codes (PS3.3 C.7.3.1.1.1).
DICOM_MODALITIES = frozenset("""
    AR ASMT AU BDUS BI BMD CR CT CTPROTOCOL DG DOC DX ECG EEG EMG EOG EPS ES
    FID GM HC HD IO IOL IVOCT IVUS KER KO LEN LS M3D MG MR NM OAM OCT OP OPM
    OPT OPTBSV OPTENF OPV OSS OT PLAN POS PR PT PX REG RESP RF RG RTDOSE
    RTIMAGE RTINTENT RTPLAN RTRAD RTRECORD RTSEGANN RTSTRUCT RWV SEG SM SMR SR
    SRF STAIN TEXTUREMAP TG US VA XA XAPROTOCOL XC
""".split())

# Codes that are also ordinary words or abbreviations in file names (DOC,
# PLAN, REG, ...) only count when they come from a DICOM tag or a person.
NAME_MODALITIES = frozenset("""
    BDUS BMD CR CT DX ECG EEG EMG EPS IVOCT IVUS MG MR NM OCT PT PX RF RG US
    XA XC
""".split())

# Other ways modalities are written in file names.
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

DICOM_DATE_TAGS = ("StudyDate", "SeriesDate", "AcquisitionDate", "ContentDate")

_DATE = re.compile(
    r"(?<!\d)((?:19|20)\d{2})[-_. ]?(0[1-9]|1[0-2])[-_. ]?(0[1-9]|[12]\d|3[01])(?!\d)"
)
_X_RAY = re.compile(r"X[-_ ]RAY", re.IGNORECASE)
_WORD = re.compile(r"[A-Za-z]+")

# `<code>_[<modality>_]<date>_<serial><rest>`: names from before modalities
# were added have no modality part.
_NAME = re.compile(
    r"^(?P<code>[A-Z0-9]+)_(?:(?P<modality>[A-Z0-9]+)_)?"
    r"(?P<day>\d{8}|UNKNOWN)_(?P<serial>\d{16})(?P<rest>.*)$"
)


@dataclass(frozen=True)
class DocumentInfo:
    modality: str = UNKNOWN
    date: str = UNKNOWN  # YYYYMMDD

    def stem(self, code: str, serial: str) -> str:
        return f"{code or 'unknown'}_{self.modality}_{self.date}_{serial}"


def clean_modality(value: Optional[str]) -> Optional[str]:
    """A known modality code for `value`, or None."""
    word = (value or "").strip().upper().replace("-", "").replace(" ", "")
    if word == UNKNOWN:
        return UNKNOWN
    word = ALIASES.get(word, word)
    return word if word in DICOM_MODALITIES else None


def clean_date(value: Optional[str]) -> Optional[str]:
    """`value` (YYYYMMDD or YYYY-MM-DD) as YYYYMMDD, or None if not a real date."""
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
    """The modality and date of a file the site sent as `name`.

    `source` is the file itself (path or bytes), read for DICOM tags. A DICOM
    file whose tags don't say falls back to its name.
    """
    from_name = DocumentInfo(
        modality=modality_from_name(name, code), date=date_from_name(name, code)
    )
    if source is None or not is_dicom_extension(extension):
        return from_name

    tags = from_dicom(source)
    return DocumentInfo(
        modality=tags.modality if tags.modality != UNKNOWN else from_name.modality,
        date=tags.date if tags.date != UNKNOWN else from_name.date,
    )


def parse_name(name: str) -> Optional[dict]:
    match = _NAME.match(name)
    return match.groupdict() if match else None


def renamed(name: str, info: DocumentInfo) -> Optional[str]:
    """`name` with its modality and date replaced, or None if it isn't one of ours."""
    parts = parse_name(name)
    if parts is None:
        return None
    return info.stem(parts["code"], parts["serial"]) + parts["rest"]


def rename(path: Path, info: DocumentInfo) -> Path:
    """Rename a redacted file and every file next to it that shares its stem
    (the intake `.json` sidecar). Returns the new path."""
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
