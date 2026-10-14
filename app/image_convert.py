from datetime import datetime, timezone
from pathlib import Path

from app import document_info
from app.logging_setup import get_logger

log = get_logger(__name__)

IMAGE_EXTENSIONS = document_info.IMAGE_EXTENSIONS
SECONDARY_CAPTURE = "1.2.840.10008.5.1.4.1.1.7"
OTHER = "OT"


class ConversionError(Exception):
    pass


def is_image(extension: str) -> bool:
    return (extension or "").lower().lstrip(".") in IMAGE_EXTENSIONS


def _pixels(path: Path):
    import numpy as np
    from PIL import Image

    try:
        image = Image.open(path)
        image.seek(0)
        image.load()
    except Exception as e:
        raise ConversionError(f"The image could not be read: {e}") from e

    if image.mode in ("I;16", "I;16B", "I;16L", "I"):
        array = np.asarray(image, dtype=np.uint32).clip(0, 65535).astype(np.uint16)
        return array, "MONOCHROME2", 16
    if image.mode in ("1", "L", "LA"):
        return np.asarray(image.convert("L"), dtype=np.uint8), "MONOCHROME2", 8
    return np.asarray(image.convert("RGB"), dtype=np.uint8), "RGB", 8


def to_dicom(source: Path, target: Path, code: str = "") -> Path:
    import pydicom
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid

    array, photometric, bits = _pixels(source)
    name = source.name
    modality = document_info.modality_from_name(name, code)
    day = document_info.date_from_name(name, code)
    now = datetime.now(timezone.utc)
    extension = source.suffix.lstrip(".").upper() or "IMAGE"

    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = SECONDARY_CAPTURE
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian

    dataset = FileDataset(str(target), {}, file_meta=meta, preamble=b"\0" * 128)
    dataset.SOPClassUID = SECONDARY_CAPTURE
    dataset.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    dataset.StudyInstanceUID = generate_uid()
    dataset.SeriesInstanceUID = generate_uid()
    dataset.PatientID = code or ""
    dataset.PatientName = code or ""
    dataset.Modality = modality if modality != document_info.UNKNOWN else OTHER
    dataset.ConversionType = "WSD"
    dataset.SeriesDescription = f"Converted from {extension}"
    dataset.ImageType = ["DERIVED", "SECONDARY"]
    dataset.SeriesNumber = 1
    dataset.InstanceNumber = 1
    if day != document_info.UNKNOWN:
        dataset.StudyDate = dataset.ContentDate = day
    dataset.InstanceCreationDate = now.strftime("%Y%m%d")
    dataset.InstanceCreationTime = now.strftime("%H%M%S")

    dataset.Rows, dataset.Columns = int(array.shape[0]), int(array.shape[1])
    dataset.PhotometricInterpretation = photometric
    dataset.SamplesPerPixel = 3 if photometric == "RGB" else 1
    if photometric == "RGB":
        dataset.PlanarConfiguration = 0
    dataset.BitsAllocated = bits
    dataset.BitsStored = bits
    dataset.HighBit = bits - 1
    dataset.PixelRepresentation = 0
    dataset.PixelData = array.tobytes()

    target.parent.mkdir(parents=True, exist_ok=True)
    pydicom.dcmwrite(str(target), dataset, enforce_file_format=True)
    log.info(
        "image_converted_to_dicom",
        modality=dataset.Modality,
        size=f"{dataset.Columns}x{dataset.Rows}",
        photometric=photometric,
    )
    return target
