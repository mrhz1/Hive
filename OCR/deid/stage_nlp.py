"""Stage 2: text in, redacted document out."""
import json
import logging
import os
import time
from dataclasses import asdict
from typing import Any, Dict, List, Optional

from deid.analyzer import analyze_text, build_analyzer
from deid.config import Config
from deid.mapping import build_page_text, map_pii_to_boxes, redact_text
from deid.documents import (
    DOCX,
    apply_redactions,
    close_document,
    kind_for,
    open_document,
    page_count,
    save_document,
    scrub_metadata,
)
from deid.results import DocumentResult, PageResult
from deid.spans import OcrDocument, PageSpans

log = logging.getLogger(__name__)


class Deidentifier:
    """Holds the loaded analyzer."""

    def __init__(self, config: Config):
        self.config = config
        self._analyzer = None
        self.whole_span = os.environ.get(
            "DEID_REDACT_WHOLE_SPAN", ""
        ).strip().lower() in ("1", "true", "yes", "on")

    @property
    def analyzer(self):
        if self._analyzer is None:
            self._analyzer = build_analyzer(self.config)
        return self._analyzer

    def redactor(self):
        """A plain str -> str redaction, for metadata values.

        The page pipeline needs each entity's offsets so it can map them
        back to pixel boxes. A metadata field has no geometry -- there is
        nothing to paint -- so it only needs the replaced text.
        """

        def redact(text: str) -> str:
            return redact_text(text, analyze_text(self.analyzer, text, self.config))

        return redact

    def process_word(
        self,
        source_path: str,
        output_path: str,
        output_text: Optional[str] = None,
        output_report: Optional[str] = None,
    ) -> DocumentResult:
        """De-identify a Word document."""
        from deid.docx_io import open_docx, read_blocks, redact_document

        started = time.perf_counter()
        result = DocumentResult(
            source_path=source_path,
            output_pdf=output_path,
            output_text=output_text,
            output_report=output_report,
        )

        try:
            document = open_docx(source_path)
        except Exception as exc:
            log.error("open failed for %s: %s", source_path, exc)
            result.status = "error"
            result.error = str(exc)
            result.failed_stage = "nlp"
            result.duration_seconds = round(time.perf_counter() - started, 2)
            return result

        counts: Dict[str, int] = {}
        values: List[dict] = []
        found = 0
        redacted_blocks: List[str] = []
        blocks: List[tuple] = []

        def redact_block(text: str) -> str:
            nonlocal found
            pii = analyze_text(self.analyzer, text, self.config)
            found += len(pii)
            for p in pii:
                counts[p.entity_type] = counts.get(p.entity_type, 0) + 1
                if self.config.report_include_values:
                    values.append(
                        {
                            "entity_type": p.entity_type,
                            "score": round(p.score, 3),
                            "text": text[p.start : p.end],
                        }
                    )
            cleaned = redact_text(text, pii)
            redacted_blocks.append(cleaned)
            return cleaned

        try:
            blocks = read_blocks(document)
            changed = redact_document(document, redact_block)

            stripped = scrub_metadata(document, DOCX, self.redactor())
            if stripped:
                log.info(
                    "metadata de-identified in %s: %s",
                    source_path,
                    ", ".join(stripped),
                )

            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
            save_document(document, DOCX, output_path)

            result.pages.append(
                PageResult(
                    page_number=1,
                    ocr_spans=len(blocks),
                    entities_found=found,
                    boxes_applied=changed,
                    entity_counts=counts,
                    entity_values=values,
                )
            )

            if output_text and self.config.write_text:
                os.makedirs(
                    os.path.dirname(os.path.abspath(output_text)), exist_ok=True
                )
                with open(output_text, "w", encoding="utf-8") as fh:
                    fh.write("\n".join(redacted_blocks))

            if output_report and self.config.write_report:
                os.makedirs(
                    os.path.dirname(os.path.abspath(output_report)), exist_ok=True
                )
                with open(output_report, "w", encoding="utf-8") as fh:
                    json.dump(self._build_word_report(result), fh, indent=2)

        except Exception as exc:
            log.exception("processing failed for %s", source_path)
            result.status = "error"
            result.error = str(exc)
            result.failed_stage = "nlp"

        result.duration_seconds = round(time.perf_counter() - started, 2)
        log.info(
            "%s -> %s | paragraphs=%d entities=%d redacted=%d %.2fs [%s]",
            source_path,
            output_path,
            len(blocks),
            result.total_entities,
            result.total_boxes,
            result.duration_seconds,
            result.status,
        )
        return result

    def _build_word_report(self, result: DocumentResult) -> dict:
        totals: Dict[str, int] = {}
        for page in result.pages:
            for entity, count in page.entity_counts.items():
                totals[entity] = totals.get(entity, 0) + count

        return {
            "source": result.source_path,
            "output": result.output_pdf,
            "format": "docx",
            "status": result.status,
            "entity_totals": totals,
            "pages": [asdict(page) for page in result.pages],
        }

    def process_document(
        self,
        ocr_document: OcrDocument,
        output_pdf: str,
        output_text: Optional[str] = None,
        output_report: Optional[str] = None,
    ) -> DocumentResult:
        started = time.perf_counter()
        source_path = ocr_document.source_path
        result = DocumentResult(
            source_path=source_path,
            output_pdf=output_pdf,
            output_text=output_text,
            output_report=output_report,
        )

        try:
            doc, kind = open_document(source_path)
        except Exception as exc:
            log.error("open failed for %s: %s", source_path, exc)
            result.status = "error"
            result.error = str(exc)
            result.failed_stage = "nlp"
            result.duration_seconds = round(time.perf_counter() - started, 2)
            return result

        text_pages: List[str] = []

        try:
            if page_count(doc, kind) != len(ocr_document.pages):
                raise RuntimeError(
                    f"page count changed since OCR ({len(ocr_document.pages)} "
                    f"scanned, {page_count(doc, kind)} now); refusing to redact"
                )

            for page_spans in ocr_document.pages:
                page_result, page_text = self._process_page(doc, kind, page_spans)
                result.pages.append(page_result)
                text_pages.append(page_text)

            stripped = scrub_metadata(doc, kind, self.redactor())
            if stripped:
                log.info(
                    "metadata de-identified in %s: %s",
                    source_path,
                    ", ".join(stripped),
                )

            os.makedirs(os.path.dirname(os.path.abspath(output_pdf)), exist_ok=True)
            save_document(doc, kind, output_pdf)

            if output_text and self.config.write_text:
                os.makedirs(
                    os.path.dirname(os.path.abspath(output_text)), exist_ok=True
                )
                with open(output_text, "w", encoding="utf-8") as fh:
                    fh.write("\n\n".join(text_pages))

            if output_report and self.config.write_report:
                os.makedirs(
                    os.path.dirname(os.path.abspath(output_report)), exist_ok=True
                )
                with open(output_report, "w", encoding="utf-8") as fh:
                    json.dump(self._build_report(result, ocr_document), fh, indent=2)

        except Exception as exc:
            log.exception("processing failed for %s", source_path)
            result.status = "error"
            result.error = str(exc)
            result.failed_stage = "nlp"
        finally:
            close_document(doc, kind)

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

    def _process_page(self, doc, kind: str, page_spans: PageSpans):
        page_text = build_page_text(page_spans.spans)
        pii = analyze_text(self.analyzer, page_text.text, self.config)

        boxes = map_pii_to_boxes(
            page_text,
            pii,
            padding=self.config.box_padding,
            whole_span=self.whole_span,
        )
        applied = apply_redactions(
            doc,
            kind,
            page_spans.page_number,
            boxes,
            page_spans.scale,
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
            page_number=page_spans.page_number,
            ocr_spans=len(page_spans.spans),
            entities_found=len(pii),
            boxes_applied=applied,
            entity_counts=counts,
            entity_values=values,
        )
        return page_result, redact_text(page_text.text, pii)

    def _build_report(
        self, result: DocumentResult, ocr_document: OcrDocument
    ) -> dict:
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
            "ocr_duration_seconds": ocr_document.duration_seconds,
            "page_count": len(result.pages),
            "total_entities": result.total_entities,
            "total_boxes_applied": result.total_boxes,
            "entity_totals": totals,
            "models": {
                "ocr_detection": ocr_document.models.get("detection"),
                "ocr_recognition": ocr_document.models.get("recognition"),
                "spacy": self.config.spacy_model,
                "transformers": self.config.transformers_model,
            },
            "settings": {
                "dpi": ocr_document.dpi,
                "score_threshold": self.config.score_threshold,
                "min_ocr_confidence": self.config.min_ocr_confidence,
                "redact_whole_span": self.whole_span,
                "box_padding": self.config.box_padding,
            },
            "pages": [asdict(p) for p in result.pages],
        }


def run_stage(jobs: List[Dict[str, Any]], config: Config) -> List[DocumentResult]:
    """Process a batch."""
    deidentifier = Deidentifier(config)
    results: List[DocumentResult] = []

    for job in jobs:
        source = job["source"]

        if kind_for(source) == DOCX:
            results.append(
                deidentifier.process_word(
                    source,
                    output_path=job["output_pdf"],
                    output_text=job.get("output_text"),
                    output_report=job.get("output_report"),
                )
            )
            continue

        try:
            ocr_document = OcrDocument.read(job["spans"])
        except Exception as exc:
            log.error("could not read OCR handoff for %s: %s", source, exc)
            results.append(
                DocumentResult(
                    source_path=source,
                    status="error",
                    error=f"could not read OCR handoff: {exc}",
                    failed_stage="nlp",
                )
            )
            continue

        results.append(
            deidentifier.process_document(
                ocr_document,
                output_pdf=job["output_pdf"],
                output_text=job.get("output_text"),
                output_report=job.get("output_report"),
            )
        )

    return results
