"""PDF rasterisation and redaction via PyMuPDF."""
import logging
from dataclasses import dataclass
from typing import List

import numpy as np

from deid.spans import RedactionBox

log = logging.getLogger(__name__)


@dataclass
class RenderedPage:
    page_number: int  # 1-based
    image: np.ndarray  # RGB
    scale: float  # image pixels per PDF point


def open_pdf(path: str):
    import fitz  # PyMuPDF

    try:
        return fitz.open(path)
    except Exception as exc:
        raise RuntimeError(f"Could not open PDF {path}: {exc}") from exc


def render_pages(doc, dpi: int):
    """Yield RenderedPage for each page, rasterised at `dpi`."""
    import fitz

    scale = dpi / 72.0
    matrix = fitz.Matrix(scale, scale)

    for page_index in range(doc.page_count):
        page = doc[page_index]
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
            pix.height, pix.width, pix.n
        )
        if pix.n == 4:  # CMYK-ish; drop to RGB
            image = image[:, :, :3]
        yield RenderedPage(
            page_number=page_index + 1, image=np.ascontiguousarray(image), scale=scale
        )


def apply_redactions(doc, page_number: int, boxes: List[RedactionBox], scale: float,
                     fill: str = "black") -> int:
    """Apply redaction annotations to one page."""
    import fitz

    if not boxes:
        return 0

    fill_map = {
        "black": (0, 0, 0),
        "white": (1, 1, 1),
    }
    fill_rgb = fill_map.get(fill.lower(), (0, 0, 0))

    page = doc[page_number - 1]
    page_rect = page.rect
    applied = 0

    for box in boxes:
        rect = fitz.Rect(
            box.x0 / scale, box.y0 / scale, box.x1 / scale, box.y1 / scale
        )
        rect = rect & page_rect
        if rect.is_empty:
            log.warning(
                "redaction box for %s fell outside page %d, skipped",
                box.entity_type,
                page_number,
            )
            continue
        page.add_redact_annot(rect, fill=fill_rgb)
        applied += 1

    if applied:
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS)

    return applied


def save_pdf(doc, output_path: str) -> None:
    try:
        # garbage/deflate keep the output tidy after content removal.
        doc.save(output_path, garbage=3, deflate=True)
    except Exception as exc:
        raise RuntimeError(f"Could not write redacted PDF {output_path}: {exc}") from exc
