"""PaddleOCR PP-OCRv6 wrapper.

Produces a flat list of OcrSpan (text + quad polygon + confidence) per
page image. Everything downstream works off these spans, so swapping OCR
engines means reimplementing only this module.
"""
import logging
from dataclasses import dataclass
from typing import List, Optional, Sequence

import numpy as np

from deid.config import Config

log = logging.getLogger(__name__)


@dataclass
class OcrSpan:
    """One recognised text run and where it sits on the page image."""

    text: str
    confidence: float
    # Axis-aligned bounds in *image pixel* coordinates.
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def bbox(self) -> tuple:
        return (self.x0, self.y0, self.x1, self.y1)


def _poly_to_bbox(poly) -> Optional[tuple]:
    """PP-OCR returns 4-point quads (rotated text is not axis aligned);
    reduce to the enclosing axis-aligned box, which is what redaction
    rectangles need."""
    try:
        arr = np.asarray(poly, dtype=float).reshape(-1, 2)
    except Exception:
        return None
    if arr.size == 0:
        return None
    return (
        float(arr[:, 0].min()),
        float(arr[:, 1].min()),
        float(arr[:, 0].max()),
        float(arr[:, 1].max()),
    )


class OcrEngine:
    """Lazy singleton-ish wrapper. PaddleOCR model load is expensive, so
    one instance is reused across every page of every PDF in a job run."""

    def __init__(self, config: Config):
        self.config = config
        self._ocr = None

    def _load(self):
        if self._ocr is not None:
            return self._ocr

        from paddleocr import PaddleOCR

        log.info(
            "loading PaddleOCR det=%s rec=%s device=%s",
            self.config.det_model,
            self.config.rec_model,
            self.config.device,
        )
        # The doc-orientation / unwarping / textline-orientation submodels
        # are off by default: they add real latency and, on the clean
        # scanned pages this job targets, change little. Turn them on via
        # env vars for skewed or photographed documents.
        self._ocr = PaddleOCR(
            text_detection_model_name=self.config.det_model,
            text_recognition_model_name=self.config.rec_model,
            use_doc_orientation_classify=self.config.use_doc_orientation_classify,
            use_doc_unwarping=self.config.use_doc_unwarping,
            use_textline_orientation=self.config.use_textline_orientation,
            # No `lang=`: PaddleOCR ignores it (with a warning) whenever
            # explicit model names are given, and PP-OCRv6 medium/small
            # are single multilingual models covering 50 languages, so
            # language selection is the model choice, not a flag.
            device=self.config.device,
            # MUST stay False on paddlepaddle 3.3.1: the oneDNN/MKLDNN
            # path crashes the PP-OCRv6 detector with
            #   NotImplementedError: ConvertPirAttribute2RuntimeAttribute
            #   not support [pir::ArrayAttribute<pir::DoubleAttribute>]
            # This flag makes PaddleX select run_mode="paddle" instead.
            # Re-test before flipping it on a newer paddlepaddle.
            enable_mkldnn=self.config.enable_mkldnn,
            cpu_threads=self.config.cpu_threads,
        )
        return self._ocr

    def read_page(self, image: np.ndarray) -> List[OcrSpan]:
        """OCR a single page image (RGB numpy array)."""
        ocr = self._load()
        try:
            results = ocr.predict(image)
        except Exception:
            log.exception("paddleocr predict failed")
            raise

        spans: List[OcrSpan] = []
        for res in results or []:
            data = getattr(res, "json", None) or {}
            # PaddleOCR 3.x nests the payload under "res" in some
            # versions and returns it flat in others -- handle both
            # rather than pinning to one shape.
            if "res" in data and isinstance(data["res"], dict):
                data = data["res"]

            texts: Sequence = data.get("rec_texts") or []
            scores: Sequence = data.get("rec_scores") or []
            polys: Sequence = data.get("rec_polys")
            if polys is None:
                polys = data.get("dt_polys") or []

            for idx, text in enumerate(texts):
                if not text or not str(text).strip():
                    continue
                score = float(scores[idx]) if idx < len(scores) else 1.0
                if score < self.config.min_ocr_confidence:
                    log.debug("dropping low-confidence OCR %r (%.2f)", text, score)
                    continue
                bbox = _poly_to_bbox(polys[idx]) if idx < len(polys) else None
                if bbox is None:
                    # No geometry means we could not redact it even if it
                    # held PII -- surfacing that is safer than silence.
                    log.warning("OCR span without polygon, skipping: %r", text)
                    continue
                spans.append(
                    OcrSpan(
                        text=str(text),
                        confidence=score,
                        x0=bbox[0],
                        y0=bbox[1],
                        x1=bbox[2],
                        y1=bbox[3],
                    )
                )

        # Reading order: top-to-bottom, then left-to-right. The joined
        # text is what Presidio sees, so ordering directly affects whether
        # multi-word entities ("John Smith") stay contiguous.
        spans.sort(key=lambda s: (round(s.y0, 1), s.x0))
        return spans
