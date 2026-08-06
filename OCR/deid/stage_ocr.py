"""Stage 1: PDF pages in, OCR spans out.

Runs under the OCR virtualenv (paddleocr + paddlepaddle + PyMuPDF) and
knows nothing about PII. It rasterises each page, recognises the text,
and writes the spans to a handoff file; stage 2 picks it up from there.

The PDF itself is *not* modified here. Redaction happens in stage 2,
against the original file, using the geometry this stage recorded --
which means a failure in the NLP stage cannot leave a half-redacted PDF
behind.
"""
import logging
import time
from typing import Any, Dict, List

from deid.config import Config
from deid.ocr_engine import OcrEngine
from deid.pdf_io import open_pdf, render_pages
from deid.spans import OcrDocument, PageSpans

log = logging.getLogger(__name__)


def ocr_document(engine: OcrEngine, source_path: str, config: Config) -> OcrDocument:
    """OCR every page of one PDF."""
    started = time.perf_counter()
    document = OcrDocument(
        source_path=source_path,
        dpi=config.dpi,
        models={
            "detection": config.det_model,
            "recognition": config.rec_model,
        },
    )

    try:
        doc = open_pdf(source_path)
    except Exception as exc:
        log.error("open failed for %s: %s", source_path, exc)
        document.status = "error"
        document.error = str(exc)
        document.duration_seconds = round(time.perf_counter() - started, 2)
        return document

    try:
        for rendered in render_pages(doc, config.dpi):
            spans = engine.read_page(rendered.image)
            document.pages.append(
                PageSpans(
                    page_number=rendered.page_number,
                    scale=rendered.scale,
                    spans=spans,
                )
            )
    except Exception as exc:
        log.exception("OCR failed for %s", source_path)
        document.status = "error"
        document.error = str(exc)
    finally:
        doc.close()

    document.duration_seconds = round(time.perf_counter() - started, 2)
    log.info(
        "ocr %s | pages=%d spans=%d %.2fs [%s]",
        source_path,
        len(document.pages),
        document.total_spans,
        document.duration_seconds,
        document.status,
    )
    return document


def run_stage(jobs: List[Dict[str, Any]], config: Config) -> List[dict]:
    """Process a batch. `jobs` is a list of {"source", "spans"} paths.

    One engine for the whole batch: PaddleOCR's model load dominates the
    cost of a small run, so a batch of 50 PDFs pays it once.

    A file that fails is recorded and the batch continues -- one corrupt
    PDF in an upload folder must not cost the other 49.
    """
    engine = OcrEngine(config)
    outcomes: List[dict] = []

    for job in jobs:
        source = job["source"]
        document = ocr_document(engine, source, config)
        try:
            document.write(job["spans"])
        except Exception as exc:
            log.exception("could not write OCR handoff for %s", source)
            document.status = "error"
            document.error = f"could not write OCR handoff: {exc}"

        outcomes.append(
            {
                "source": source,
                "spans": job["spans"],
                "status": document.status,
                "error": document.error,
                "pages": len(document.pages),
                "spans_found": document.total_spans,
                "duration_seconds": document.duration_seconds,
            }
        )

    return outcomes
