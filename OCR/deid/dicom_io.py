import logging
import os
import secrets
from typing import Dict, List, Optional, Sequence

import numpy as np

from deid.spans import RedactionBox

log = logging.getLogger(__name__)

PHI_TAGS = (
    "AccessionNumber",
    "AdmissionID",
    "AdmittingDiagnosesDescription",
    "BranchOfService",
    "CountryOfResidence",
    "CurrentPatientLocation",
    "InstitutionAddress",
    "InstitutionName",
    "InstitutionalDepartmentName",
    "IssuerOfPatientID",
    "MilitaryRank",
    "NameOfPhysiciansReadingStudy",
    "OperatorsName",
    "OtherPatientIDs",
    "OtherPatientIDsSequence",
    "OtherPatientNames",
    "PatientAddress",
    "PatientBirthDate",
    "PatientBirthName",
    "PatientBirthTime",
    "PatientComments",
    "PatientID",
    "PatientInsurancePlanCodeSequence",
    "PatientMotherBirthName",
    "PatientName",
    "PatientReligiousPreference",
    "PatientSex",
    "PatientTelephoneNumbers",
    "PatientTelecomInformation",
    "PerformingPhysicianName",
    "PhysiciansOfRecord",
    "ReferringPhysicianAddress",
    "ReferringPhysicianName",
    "ReferringPhysicianTelephoneNumbers",
    "RegionOfResidence",
    "RequestingPhysician",
    "ResponsiblePerson",
    "ResponsibleOrganization",
    "StudyID",
)

BLANKED_TAGS = (
    "AcquisitionDate",
    "AcquisitionDateTime",
    "AcquisitionTime",
    "ContentDate",
    "ContentTime",
    "SeriesDate",
    "SeriesTime",
    "StudyDate",
    "StudyTime",
)


def open_dicom(path: str):
    import pydicom

    try:
        dataset = pydicom.dcmread(path, force=True)
    except Exception as exc:
        raise RuntimeError(f"Could not open DICOM {path}: {exc}") from exc
    if fix_photometric(dataset):
        log.info("%s says YBR_FULL_422 but holds full-size pixels; read as YBR_FULL", path)
    return dataset


def _full_size_bytes(dataset) -> int:
    return (
        int(dataset.Rows)
        * int(dataset.Columns)
        * int(getattr(dataset, "SamplesPerPixel", 1) or 1)
        * (int(dataset.BitsAllocated) // 8)
        * int(getattr(dataset, "NumberOfFrames", 1) or 1)
    )


def fix_photometric(dataset) -> bool:
    if getattr(dataset, "PhotometricInterpretation", "") != "YBR_FULL_422":
        return False
    if "PixelData" not in dataset:
        return False
    syntax = getattr(getattr(dataset, "file_meta", None), "TransferSyntaxUID", None)
    if syntax is not None and syntax.is_compressed:
        return False
    try:
        full = _full_size_bytes(dataset)
    except (AttributeError, TypeError, ValueError):
        return False
    if len(dataset.PixelData) < full:
        return False
    dataset.PhotometricInterpretation = "YBR_FULL"
    return True


def has_pixels(dataset) -> bool:
    return "PixelData" in dataset


def _to_rgb(frame: np.ndarray) -> np.ndarray:
    array = frame

    if array.dtype != np.uint8:
        array = array.astype(np.float32)
        low, high = float(array.min()), float(array.max())
        if high > low:
            array = (array - low) / (high - low)
        else:
            array = np.zeros_like(array)
        array = (array * 255.0).astype(np.uint8)

    if array.ndim == 2:
        array = np.stack([array] * 3, axis=-1)
    elif array.ndim == 3 and array.shape[-1] == 1:
        array = np.repeat(array, 3, axis=-1)
    elif array.ndim == 3 and array.shape[-1] > 3:
        array = array[:, :, :3]

    return np.ascontiguousarray(array)


def frames(dataset) -> List[np.ndarray]:
    if not has_pixels(dataset):
        return []

    try:
        pixels = dataset.pixel_array
    except Exception as exc:
        raise RuntimeError(f"Could not decode DICOM pixel data: {exc}") from exc

    number_of_frames = int(getattr(dataset, "NumberOfFrames", 1) or 1)
    samples = int(getattr(dataset, "SamplesPerPixel", 1) or 1)

    if number_of_frames > 1:
        return [pixels[index] for index in range(number_of_frames)]

    if pixels.ndim == 3 and samples == 1:
        return [pixels[index] for index in range(pixels.shape[0])]

    return [pixels]


def frames_to_ocr(total: int, mode: str) -> List[int]:
    from deid.config import DICOM_FRAME_OCR_ALL, DICOM_FRAME_OCR_FIRST

    if total <= 0:
        return []
    if mode == DICOM_FRAME_OCR_ALL:
        return list(range(1, total + 1))
    if mode == DICOM_FRAME_OCR_FIRST:
        return [1]
    return sorted({1, total})


def render_frames(dataset, _dpi: int = 0, only: Optional[Sequence[int]] = None):
    from deid.pdf_io import RenderedPage

    wanted = set(only) if only is not None else None
    for index, frame in enumerate(frames(dataset)):
        if wanted is not None and index + 1 not in wanted:
            continue
        yield RenderedPage(
            page_number=index + 1, image=_to_rgb(frame), scale=1.0
        )


def apply_redactions(
    dataset,
    page_number: int,
    boxes: List[RedactionBox],
    scale: float = 1.0,
    fill: str = "black",
) -> int:
    if not boxes:
        return 0
    if not has_pixels(dataset):
        log.warning("DICOM has no pixel data; nothing to redact on frame %d", page_number)
        return 0

    pixels = dataset.pixel_array
    number_of_frames = int(getattr(dataset, "NumberOfFrames", 1) or 1)
    samples = int(getattr(dataset, "SamplesPerPixel", 1) or 1)
    multi_frame = number_of_frames > 1 or (pixels.ndim == 3 and samples == 1)

    frame = pixels[page_number - 1] if multi_frame else pixels
    height, width = frame.shape[0], frame.shape[1]

    value = 0 if fill.lower() == "black" else int(np.iinfo(frame.dtype).max)
    applied = 0

    for box in boxes:
        x0 = max(0, int(box.x0 / scale))
        y0 = max(0, int(box.y0 / scale))
        x1 = min(width, int(round(box.x1 / scale)))
        y1 = min(height, int(round(box.y1 / scale)))

        if x1 <= x0 or y1 <= y0:
            log.warning(
                "redaction box for %s fell outside frame %d, skipped",
                box.entity_type,
                page_number,
            )
            continue

        frame[y0:y1, x0:x1] = value
        applied += 1

    if applied:
        if multi_frame:
            pixels[page_number - 1] = frame
        dataset.PixelData = pixels.tobytes()
        dataset.file_meta.TransferSyntaxUID = _EXPLICIT_VR_LITTLE_ENDIAN()
        if "PlanarConfiguration" in dataset and samples > 1:
            dataset.PlanarConfiguration = 0
        if samples > 1 and str(dataset.PhotometricInterpretation).startswith("YBR"):
            dataset.PhotometricInterpretation = "RGB"

    return applied


def _paint_frames(dataset, boxes_for, scale: float, fill: str) -> Dict[int, int]:
    if not has_pixels(dataset):
        log.warning("DICOM has no pixel data; nothing to redact")
        return {}

    pixels = dataset.pixel_array
    number_of_frames = int(getattr(dataset, "NumberOfFrames", 1) or 1)
    samples = int(getattr(dataset, "SamplesPerPixel", 1) or 1)
    multi_frame = number_of_frames > 1 or (pixels.ndim == 3 and samples == 1)
    total = pixels.shape[0] if multi_frame else 1

    height = pixels.shape[1] if multi_frame else pixels.shape[0]
    width = pixels.shape[2] if multi_frame else pixels.shape[1]
    value = 0 if fill.lower() == "black" else int(np.iinfo(pixels.dtype).max)

    boxes_by_frame = boxes_for(total)
    applied: Dict[int, int] = {number: 0 for number in boxes_by_frame}

    for number, boxes in boxes_by_frame.items():
        if not 1 <= number <= total:
            log.warning("frame %d is not in the DICOM, skipped", number)
            continue
        frame = pixels[number - 1] if multi_frame else pixels
        for box in boxes:
            x0 = max(0, int(box.x0 / scale))
            y0 = max(0, int(box.y0 / scale))
            x1 = min(width, int(round(box.x1 / scale)))
            y1 = min(height, int(round(box.y1 / scale)))

            if x1 <= x0 or y1 <= y0:
                log.warning(
                    "redaction box for %s fell outside frame %d, skipped",
                    box.entity_type,
                    number,
                )
                continue

            frame[y0:y1, x0:x1] = value
            applied[number] += 1

    if any(applied.values()):
        dataset.PixelData = pixels.tobytes()
        dataset.file_meta.TransferSyntaxUID = _EXPLICIT_VR_LITTLE_ENDIAN()
        if "PlanarConfiguration" in dataset and samples > 1:
            dataset.PlanarConfiguration = 0
        if samples > 1 and str(dataset.PhotometricInterpretation).startswith("YBR"):
            dataset.PhotometricInterpretation = "RGB"

    return applied


def redact_frames(
    dataset,
    boxes_by_frame: Dict[int, List[RedactionBox]],
    scale: float = 1.0,
    fill: str = "black",
) -> Dict[int, int]:
    if not any(boxes_by_frame.values()):
        return {number: 0 for number in boxes_by_frame}
    applied = _paint_frames(dataset, lambda total: boxes_by_frame, scale, fill)
    return {number: applied.get(number, 0) for number in boxes_by_frame}


def redact_all_frames(
    dataset,
    boxes: List[RedactionBox],
    scale: float = 1.0,
    fill: str = "black",
) -> Dict[int, int]:
    if not boxes:
        return {}
    return _paint_frames(
        dataset,
        lambda total: {number: boxes for number in range(1, total + 1)},
        scale,
        fill,
    )


def _EXPLICIT_VR_LITTLE_ENDIAN():
    from pydicom.uid import ExplicitVRLittleEndian

    return ExplicitVRLittleEndian


_REDACTABLE_VR_LIMITS = {
    "LO": 64,
    "LT": 10240,
    "PN": 64,
    "SH": 16,
    "ST": 1024,
    "UC": 0,
    "UT": 0,
}

_STRUCTURAL_VRS = frozenset({"UI", "OB", "OW", "OD", "OF", "OL", "OV", "UN", "SQ"})

NEVER_MODIFIED = frozenset(
    {
        "BitsAllocated",
        "BitsStored",
        "Columns",
        "HighBit",
        "NumberOfFrames",
        "PhotometricInterpretation",
        "PixelAspectRatio",
        "PixelRepresentation",
        "PlanarConfiguration",
        "RescaleIntercept",
        "RescaleSlope",
        "RescaleType",
        "Rows",
        "SamplesPerPixel",
        "SmallestImagePixelValue",
        "LargestImagePixelValue",
        "TransferSyntaxUID",
        "WindowCenter",
        "WindowWidth",
        "VOILUTFunction",
    }
)

_PHI_TAG_SET = frozenset(PHI_TAGS)
_BLANKED_TAG_SET = frozenset(BLANKED_TAGS)


def _fit(value: str, vr: str) -> str:
    limit = _REDACTABLE_VR_LIMITS.get(vr, 0)
    return value[:limit] if limit else value


def _deidentify_element(element, redact, touched: List[str], prefix: str = "") -> None:
    from deid.metadata import PLACEHOLDER, deidentify_value

    keyword = element.keyword or str(element.tag)
    label = f"{prefix}{keyword}"
    known_phi = keyword in _PHI_TAG_SET

    if keyword in NEVER_MODIFIED or element.VR in _STRUCTURAL_VRS:
        return

    if element.VR not in _REDACTABLE_VR_LIMITS:
        if known_phi or keyword in _BLANKED_TAG_SET:
            if element.value not in (None, ""):
                element.value = ""
                touched.append(label)
        return

    if element.VM > 1 and isinstance(element.value, (list, tuple)):
        values = [str(item) for item in element.value]
        cleaned = [
            deidentify_value(item, redact, known_phi) or item for item in values
        ]
        if cleaned != values:
            element.value = [_fit(item, element.VR) for item in cleaned]
            touched.append(label)
        return

    replacement = deidentify_value(element.value, redact, known_phi)
    if replacement is not None:
        element.value = _fit(replacement, element.VR)
        touched.append(label)
    elif known_phi and str(element.value or "").strip():
        element.value = _fit(PLACEHOLDER, element.VR)
        touched.append(label)


def _walk(dataset, redact, touched: List[str], prefix: str = "", depth: int = 0) -> None:
    if depth > 8:
        return

    for element in dataset:
        if element.tag == 0x7FE00010:
            continue

        if element.VR == "SQ":
            for index, item in enumerate(element.value or []):
                _walk(
                    item,
                    redact,
                    touched,
                    f"{prefix}{element.keyword or element.tag}[{index}].",
                    depth + 1,
                )
            continue

        _deidentify_element(element, redact, touched, prefix)


_KEPT_UID_KEYWORDS = frozenset(
    {"ImplementationClassUID", "TransferSyntaxUID", "CodingSchemeUID"}
)

_RUN_SALT = secrets.token_hex(16)
_warned_no_salt = False


def _uid_salt() -> str:
    global _warned_no_salt
    salt = os.environ.get("DEID_UID_SALT")
    if salt:
        return salt
    if not _warned_no_salt:
        log.warning("DEID_UID_SALT is not set; new UIDs are random per run")
        _warned_no_salt = True
    return _RUN_SALT


def _is_standard_uid(value: str) -> bool:
    from pydicom._uid_dict import UID_dictionary

    return value in UID_dictionary


def _new_uid(value: str, salt: str) -> str:
    from pydicom.uid import generate_uid

    return str(generate_uid(entropy_srcs=[salt, value]))


def _replace_uids(dataset, salt: str, touched: List[str], prefix: str = "", depth: int = 0) -> None:
    if depth > 8:
        return
    for element in dataset:
        if element.VR == "SQ":
            for index, item in enumerate(element.value or []):
                _replace_uids(item, salt, touched,
                              f"{prefix}{element.keyword or element.tag}[{index}].", depth + 1)
            continue
        if element.VR != "UI" or element.keyword in _KEPT_UID_KEYWORDS:
            continue
        values = element.value if element.VM > 1 else [element.value]
        values = [str(v) for v in values if v not in (None, "")]
        if not values or all(_is_standard_uid(v) for v in values):
            continue
        new = [v if _is_standard_uid(v) else _new_uid(v, salt) for v in values]
        element.value = new if element.VM > 1 else new[0]
        touched.append(f"{prefix}{element.keyword or element.tag}")


def scrub_metadata(dataset, redact=None) -> List[str]:
    touched: List[str] = []

    if redact is None:
        def redact(text: str) -> str:
            return text

    try:
        _walk(dataset, redact, touched)
    except Exception as exc:
        log.warning("metadata de-identification pass failed: %s", exc)

    try:
        dataset.remove_private_tags()
        touched.append("<private tags>")
    except Exception as exc:
        log.warning("could not remove private tags: %s", exc)

    salt = _uid_salt()
    try:
        _replace_uids(dataset, salt, touched)
        meta = getattr(dataset, "file_meta", None)
        if meta is not None and "MediaStorageSOPInstanceUID" in meta:
            meta.MediaStorageSOPInstanceUID = _new_uid(str(meta.MediaStorageSOPInstanceUID), salt)
    except Exception as exc:
        log.warning("UID de-identification failed: %s", exc)

    dataset.PatientIdentityRemoved = "YES"
    dataset.DeidentificationMethod = "Hive OCR/NER pixel and tag de-identification"

    return touched


def save_dicom(dataset, output_path: str) -> None:
    try:
        dataset.save_as(output_path, enforce_file_format=True)
    except TypeError:
        dataset.save_as(output_path, write_like_original=False)
    except Exception as exc:
        raise RuntimeError(
            f"Could not write redacted DICOM {output_path}: {exc}"
        ) from exc
