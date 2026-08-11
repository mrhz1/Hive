"""DICOM rasterisation, pixel redaction and tag scrubbing via pydicom."""
import logging
from typing import List

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
        return pydicom.dcmread(path, force=True)
    except Exception as exc:
        raise RuntimeError(f"Could not open DICOM {path}: {exc}") from exc


def has_pixels(dataset) -> bool:
    return "PixelData" in dataset


def _to_rgb(frame: np.ndarray) -> np.ndarray:
    """One frame as contiguous 8-bit RGB, whatever it started as."""
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
    """Pixel data as a list of frames, one entry for a single-frame study."""
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


def render_frames(dataset, _dpi: int = 0):
    """Yield RenderedPage per frame."""
    from deid.pdf_io import RenderedPage

    for index, frame in enumerate(frames(dataset)):
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
    """Paint boxes into the stored pixel data."""
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

    return applied


def _EXPLICIT_VR_LITTLE_ENDIAN():
    from pydicom.uid import ExplicitVRLittleEndian

    return ExplicitVRLittleEndian


# VRs that hold free text a placeholder can legally be written into,
# with the length the standard allows for each.
_TEXT_VR_LIMITS = {
    "AE": 16,
    "CS": 16,
    "LO": 64,
    "LT": 10240,
    "PN": 64,
    "SH": 16,
    "ST": 1024,
    "UC": 0,   # unlimited
    "UT": 0,
}

# Dates, times and numbers cannot hold '<PATIENT>' -- a reader that
# parses them would choke. They are emptied instead, which every one of
# these VRs accepts.
_EMPTIED_VRS = frozenset(
    {"DA", "DT", "TM", "AS", "IS", "DS", "US", "SS", "UL", "SL", "FL", "FD"}
)

# Never rewritten: UIDs are structural. Blanking SOPInstanceUID or the
# transfer syntax produces a file nothing will open, and they identify a
# study rather than a person.
_STRUCTURAL_VRS = frozenset({"UI", "OB", "OW", "OD", "OF", "OL", "OV", "UN", "SQ"})

_PHI_TAG_SET = frozenset(PHI_TAGS)
_BLANKED_TAG_SET = frozenset(BLANKED_TAGS)


def _fit(value: str, vr: str) -> str:
    limit = _TEXT_VR_LIMITS.get(vr, 0)
    return value[:limit] if limit else value


def _deidentify_element(element, redact, touched: List[str], prefix: str = "") -> None:
    """De-identify one element in place, respecting what its VR can hold."""
    from deid.metadata import PLACEHOLDER, deidentify_value

    keyword = element.keyword or str(element.tag)
    label = f"{prefix}{keyword}"
    known_phi = keyword in _PHI_TAG_SET

    if element.VR in _STRUCTURAL_VRS:
        return

    if element.VR in _EMPTIED_VRS:
        # A date is identifying on its own -- birth dates especially --
        # so the known list still empties these outright.
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
        # Belt and braces: a known-PHI field never keeps its own value.
        element.value = _fit(PLACEHOLDER, element.VR)
        touched.append(label)


def _walk(dataset, redact, touched: List[str], prefix: str = "", depth: int = 0) -> None:
    """Every element, sequences included. PHI hides in nested datasets too."""
    if depth > 8:  # pragma: no cover - guards a pathological file
        return

    for element in dataset:
        if element.tag == 0x7FE00010:  # PixelData: handled by the redactor
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


def scrub_metadata(dataset, redact=None) -> List[str]:
    """De-identify the tags in place, keeping the study readable.

    `redact` is the same analyzer-backed callable the page text goes
    through. Without one this falls back to the old behaviour -- a
    known-PHI tag is emptied rather than de-identified -- so a caller
    that has no analyzer still produces a safe file.
    """
    touched: List[str] = []

    if redact is None:
        def redact(text: str) -> str:  # noqa: E306 - local fallback
            return text

    try:
        _walk(dataset, redact, touched)
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("metadata de-identification pass failed: %s", exc)

    # Private tags are vendor-defined: their contents cannot be checked
    # against anything, so they still go entirely.
    try:
        dataset.remove_private_tags()
        touched.append("<private tags>")
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("could not remove private tags: %s", exc)

    dataset.PatientIdentityRemoved = "YES"
    dataset.DeidentificationMethod = "Hive OCR/NER pixel and tag de-identification"

    return touched


def save_dicom(dataset, output_path: str) -> None:
    try:
        dataset.save_as(output_path, enforce_file_format=True)
    except TypeError:
        # pydicom < 3 spells it differently.
        dataset.save_as(output_path, write_like_original=False)
    except Exception as exc:
        raise RuntimeError(
            f"Could not write redacted DICOM {output_path}: {exc}"
        ) from exc
