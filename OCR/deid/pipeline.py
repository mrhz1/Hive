"""Orchestration: PDF in, de-identified PDF (+ text + report) out.

Per page: rasterise -> OCR -> join to text -> Presidio analyse -> map
entities back to boxes -> redact. Models are loaded once and reused
across every page and every file in a run, which dominates cost.
"""
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

from deid.analyzer import analyze_text, build_analyzer
from deid.config import Config
from deid.mapping import build_page_text, map_pii_to_boxes, redact_text
from deid.ocr_engine import OcrEngine
from deid.pdf_io import apply_redactions, open_pdf, render_pages, save_pdf

log = logging.getLogger(__name__)


@dataclass
class PageResult:
    page_number: int
    ocr_spans: int
    entities_found: int
    boxes_applied: int
    entity_counts: Dict[str, int] = field(default_factory=dict)
    # Populated only when config.report_include_values is on.
    entity_values: List[dict] = field(default_factory=list)


@dataclass
class DocumentResult:
    source_path: str
    output_pdf: Optional[str]
    output_text: Optional[str]
    output_report: Optional[str]
    pages: List[PageResult] = field(default_factory=list)
    duration_seconds: float = 0.0
    status: str = "ok"
    error: Optional[str] = None

    @property
    def total_entities(self) -> int:
        return sum(p.entities_found for p in self.pages)

    @property
    def total_boxes(self) -> int:
        return sum(p.boxes_applied for p in self.pages)


class Deidentifier:
    """Holds the loaded models. Construct once per job, call
    process_pdf per file."""

    def __init__(self, config: Config):
        self.config = config
        self.ocr = OcrEngine(config)
        self._analyzer = None
        # Whole-span redaction is the conservative mode: cover the entire
        # OCR line whenever any part of it is PII. Default is the
        # proportional estimate, which keeps non-PII text readable.
        self.whole_span = os.environ.get(
            "DEID_REDACT_WHOLE_SPAN", ""
        ).strip().lower() in ("1", "true", "yes", "on")

    @property
    def analyzer(self):
        if self._analyzer is None:
            self._analyzer = build_analyzer(self.config)
        return self._analyzer

    def process_pdf(
        self, source_path: str, output_pdf: str,
        output_text: Optional[str] = None,
        output_report: Optional[str] = None,
    ) -> DocumentResult:
        started = time.perf_counter()
        result = DocumentResult(
            source_path=source_path,
            output_pdf=output_pdf,
            output_text=output_text,
            output_report=output_report,
        )

        try:
            doc = open_pdf(source_path)
        except Exception as exc:
            log.error("open failed for %s: %s", source_path, exc)
            result.status = "error"
            result.error = str(exc)
            result.duration_seconds = time.perf_counter() - started
            return result

        text_pages: List[str] = []

        try:
            for rendered in render_pages(doc, self.config.dpi):
                page_result, page_text = self._process_page(doc, rendered)
                result.pages.append(page_result)
                text_pages.append(page_text)

            os.makedirs(os.path.dirname(os.path.abspath(output_pdf)), exist_ok=True)
            save_pdf(doc, output_pdf)

            if output_text and self.config.write_text:
                os.makedirs(os.path.dirname(os.path.abspath(output_text)), exist_ok=True)
                with open(output_text, "w", encoding="utf-8") as fh:
                    fh.write("\n\n".join(text_pages))

            if output_report and self.config.write_report:
                os.makedirs(
                    os.path.dirname(os.path.abspath(output_report)), exist_ok=True
                )
                with open(output_report, "w", encoding="utf-8") as fh:
                    json.dump(self._build_report(result), fh, indent=2)

        except Exception as exc:
            log.exception("processing failed for %s", source_path)
            result.status = "error"
            result.error = str(exc)
        finally:
            doc.close()

        result.duration_seconds = round(time.perf_counter() - started, 2)
        log.info(
            "%s -> %s | pages=%d entities=%d boxes=%d %.2fs [%s]",
            source_path,
            output_pdf,
            len(result.pages),
            result.total_entities,
            result.total_boxes,
            result.duration_seconds,
            result.status,
        )
        return result

    def _process_page(self, doc, rendered):
        spans = self.ocr.read_page(rendered.image)
        page_text = build_page_text(spans)
        pii = analyze_text(self.analyzer, page_text.text, self.config)

        boxes = map_pii_to_boxes(
            page_text,
            pii,
            padding=self.config.box_padding,
            whole_span=self.whole_span,
        )
        applied = apply_redactions(
            doc,
            rendered.page_number,
            boxes,
            rendered.scale,
            fill=self.config.redaction_fill,
        )

        counts: Dict[str, int] = {}
        for p in pii:
            counts[p.entity_type] = counts.get(p.entity_type, 0) + 1

        values: List[dict] = []
        if self.config.report_include_values:
            values = [
                {
                    "entity_type": p.entity_type,
                    "score": round(p.score, 3),
                    "text": page_text.text[p.start : p.end],
                }
                for p in pii
            ]

        page_result = PageResult(
            page_number=rendered.page_number,
            ocr_spans=len(spans),
            entities_found=len(pii),
            boxes_applied=applied,
            entity_counts=counts,
            entity_values=values,
        )
        return page_result, redact_text(page_text.text, pii)

    def _build_report(self, result: DocumentResult) -> dict:
        totals: Dict[str, int] = {}
        for page in result.pages:
            for entity, count in page.entity_counts.items():
                totals[entity] = totals.get(entity, 0) + count

        return {
            "source_path": result.source_path,
            "output_pdf": result.output_pdf,
            "status": result.status,
            "error": result.error,
            "duration_seconds": result.duration_seconds,
            "page_count": len(result.pages),
            "total_entities": result.total_entities,
            "total_boxes_applied": result.total_boxes,
            "entity_totals": totals,
            "models": {
                "ocr_detection": self.config.det_model,
                "ocr_recognition": self.config.rec_model,
                "spacy": self.config.spacy_model,
                "transformers": self.config.transformers_model,
            },
            "settings": {
                "dpi": self.config.dpi,
                "score_threshold": self.config.score_threshold,
                "min_ocr_confidence": self.config.min_ocr_confidence,
                "redact_whole_span": self.whole_span,
                "box_padding": self.config.box_padding,
            },
            "pages": [asdict(p) for p in result.pages],
        }
