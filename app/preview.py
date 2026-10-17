from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Tuple

from app.errors import ValidationError
from app.logging_setup import get_logger, ref

log = get_logger(__name__)

MAX_DIMENSION = 2400

MAX_PARAGRAPHS = 2000
MAX_TABLE_ROWS = 500


def _fix_photometric(dataset) -> None:
    if str(getattr(dataset, "PhotometricInterpretation", "")) != "YBR_FULL_422":
        return
    syntax = getattr(getattr(dataset, "file_meta", None), "TransferSyntaxUID", None)
    if syntax is not None and syntax.is_compressed:
        return
    try:
        full = (
            int(dataset.Rows)
            * int(dataset.Columns)
            * int(getattr(dataset, "SamplesPerPixel", 1) or 1)
            * (int(dataset.BitsAllocated) // 8)
            * int(getattr(dataset, "NumberOfFrames", 1) or 1)
        )
    except (AttributeError, TypeError, ValueError):
        return
    if len(dataset.PixelData) >= full:
        dataset.PhotometricInterpretation = "YBR_FULL"


def _decode(dataset, frame_index: int):
    from pydicom.pixels import pixel_array

    declared = int(getattr(dataset, "NumberOfFrames", 1) or 1)
    try:
        if declared > 1:
            if frame_index < 0 or frame_index >= declared:
                raise ValidationError(
                    f"Frame {frame_index} does not exist; this study has {declared}"
                )
            return pixel_array(dataset, index=frame_index), declared
        pixels = dataset.pixel_array
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError(
            f"This DICOM's pixel data could not be decoded: {exc}"
        ) from exc

    total = frame_number(dataset, pixels)
    if frame_index < 0 or frame_index >= total:
        raise ValidationError(f"Frame {frame_index} does not exist; this study has {total}")
    samples = int(getattr(dataset, "SamplesPerPixel", 1) or 1)
    if pixels.ndim == 3 and samples == 1:
        return pixels[frame_index], total
    return pixels, total


def _to_display_array(dataset, frame):
    import numpy as np

    samples = int(getattr(dataset, "SamplesPerPixel", 1) or 1)
    if samples == 1:
        try:
            from pydicom.pixels import apply_voi_lut

            frame = apply_voi_lut(frame, dataset, index=0)
        except Exception:
            pass

    frame = np.asarray(frame)

    if frame.dtype != np.uint8:
        low, high = float(frame.min()), float(frame.max())
        if high > low:
            frame = (frame.astype(np.float64) - low) / (high - low)
        else:
            frame = np.zeros_like(frame, dtype=np.float64)
        frame = (frame * 255.0).astype(np.uint8)

    if str(getattr(dataset, "PhotometricInterpretation", "")) == "MONOCHROME1":
        frame = 255 - frame

    return frame


def frame_number(dataset, pixels=None) -> int:
    declared = int(getattr(dataset, "NumberOfFrames", 1) or 1)
    if declared > 1:
        return declared

    if pixels is not None:
        samples = int(getattr(dataset, "SamplesPerPixel", 1) or 1)
        if pixels.ndim == 3 and samples == 1:
            return int(pixels.shape[0])

    return 1


def render_dicom_png(path: Path, frame_index: int = 0) -> Tuple[bytes, int]:
    stat = Path(path).stat()
    return _render_dicom_png(str(path), stat.st_mtime_ns, stat.st_size, frame_index)


@lru_cache(maxsize=96)
def _render_dicom_png(path: str, _mtime_ns: int, _size: int, frame_index: int) -> Tuple[bytes, int]:
    import pydicom
    from PIL import Image

    try:
        dataset = pydicom.dcmread(path, force=True)
    except Exception as exc:
        raise ValidationError(f"This file is not readable as DICOM: {exc}") from exc

    if not hasattr(dataset, "PixelData"):
        raise ValidationError("This DICOM carries no image data to display")

    _fix_photometric(dataset)
    frame, total = _decode(dataset, frame_index)
    array = _to_display_array(dataset, frame)

    image = Image.fromarray(array)
    if image.mode not in ("L", "RGB"):
        image = image.convert("RGB")

    if max(image.size) > MAX_DIMENSION:
        image.thumbnail((MAX_DIMENSION, MAX_DIMENSION))

    from io import BytesIO

    buffer = BytesIO()
    image.save(buffer, format="PNG")

    log.info("dicom_rendered", file_ref=ref(path), frame=frame_index, frames=total, size=image.size)
    return buffer.getvalue(), total


def _table_rows(table) -> List[List[str]]:
    rows = []
    for row in table.rows[:MAX_TABLE_ROWS]:
        rows.append([cell.text.strip() for cell in row.cells])
    return rows


def read_word_document(path: Path) -> Dict:
    import docx

    try:
        document = docx.Document(str(path))
    except Exception as exc:
        raise ValidationError(
            "This Word document could not be opened. Only the 2007+ .docx "
            f"format can be previewed: {exc}"
        ) from exc

    blocks = []
    for paragraph in document.paragraphs[:MAX_PARAGRAPHS]:
        text = paragraph.text.strip()
        if not text:
            continue
        blocks.append(
            {
                "kind": "heading" if paragraph.style.name.startswith("Heading") else "paragraph",
                "style": paragraph.style.name,
                "text": text,
            }
        )

    tables = [_table_rows(table) for table in document.tables]

    log.info(
        "word_document_read",
        path=str(path),
        blocks=len(blocks),
        tables=len(tables),
    )
    return {
        "blocks": blocks,
        "tables": tables,
        "truncated": len(document.paragraphs) > MAX_PARAGRAPHS,
    }
