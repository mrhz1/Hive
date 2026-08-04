"""Bridge between OCR geometry and Presidio character offsets.

Presidio works on a flat string; redaction needs pixel rectangles. This
module builds the page string from OCR spans while remembering where each
span landed in it, then walks detected entities back to boxes.
"""
import logging
from dataclasses import dataclass, field
from typing import List, Tuple

from deid.analyzer import PiiSpan
from deid.ocr_engine import OcrSpan

log = logging.getLogger(__name__)

# Spans are text lines, so joining with a newline preserves the line
# structure the NER model benefits from. Length must be accounted for
# when computing offsets.
SEPARATOR = "\n"


@dataclass
class PageText:
    text: str
    # (char_start, char_end, span) per OCR span, in text order.
    index: List[Tuple[int, int, OcrSpan]] = field(default_factory=list)


def build_page_text(spans: List[OcrSpan]) -> PageText:
    parts: List[str] = []
    index: List[Tuple[int, int, OcrSpan]] = []
    cursor = 0

    for i, span in enumerate(spans):
        if i > 0:
            cursor += len(SEPARATOR)
        start = cursor
        end = start + len(span.text)
        index.append((start, end, span))
        parts.append(span.text)
        cursor = end

    return PageText(text=SEPARATOR.join(parts), index=index)


@dataclass
class RedactionBox:
    x0: float
    y0: float
    x1: float
    y1: float
    entity_type: str
    score: float


def _sub_box(
    span: OcrSpan, local_start: int, local_end: int, whole_span: bool
) -> Tuple[float, float]:
    """Horizontal extent to redact within one OCR span.

    Characters are assumed to be evenly distributed across the span's
    width. That is an approximation -- proportional fonts are not
    uniform -- which is why callers pad the result. Set whole_span to
    ignore the estimate and cover the entire span.
    """
    if whole_span:
        return span.x0, span.x1

    length = len(span.text)
    if length <= 0:
        return span.x0, span.x1

    width = span.x1 - span.x0
    char_w = width / length
    x_start = span.x0 + max(0, local_start) * char_w
    x_end = span.x0 + min(length, local_end) * char_w
    if x_end <= x_start:
        return span.x0, span.x1
    return x_start, x_end


def map_pii_to_boxes(
    page_text: PageText,
    pii_spans: List[PiiSpan],
    padding: float = 2.0,
    whole_span: bool = False,
) -> List[RedactionBox]:
    """Turn character-offset detections into pixel rectangles.

    A single entity can straddle several OCR spans (a name wrapped across
    two lines), so every overlapping span contributes a box.
    """
    boxes: List[RedactionBox] = []

    for pii in pii_spans:
        matched = False
        for start, end, span in page_text.index:
            # Half-open interval overlap.
            if pii.start >= end or pii.end <= start:
                continue
            matched = True

            local_start = pii.start - start
            local_end = pii.end - start
            x0, x1 = _sub_box(span, local_start, local_end, whole_span)

            boxes.append(
                RedactionBox(
                    x0=x0 - padding,
                    y0=span.y0 - padding,
                    x1=x1 + padding,
                    y1=span.y1 + padding,
                    entity_type=pii.entity_type,
                    score=pii.score,
                )
            )

        if not matched:
            # Should not happen -- the text came from these spans -- but a
            # silent miss here is an un-redacted entity, so make noise.
            log.warning(
                "PII %s at [%d,%d) matched no OCR span; NOT redacted",
                pii.entity_type,
                pii.start,
                pii.end,
            )

    return boxes


def redact_text(text: str, pii_spans: List[PiiSpan]) -> str:
    """Produce the de-identified text, replacing each entity with its
    type tag. Applied right-to-left so earlier offsets stay valid."""
    out = text
    for pii in sorted(pii_spans, key=lambda s: s.start, reverse=True):
        out = out[: pii.start] + f"<{pii.entity_type}>" + out[pii.end :]
    return out
