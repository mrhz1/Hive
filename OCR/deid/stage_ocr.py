"""Stage 1: raster pages in, OCR spans out."""
import logging
import time
from typing import Any, Dict, List

from deid.config import Config
from deid.ocr_engine import OcrEngine
from deid.documents import close_document, open_document, page_count, render_pages
from deid.progress import NullProgress, writer as progress_writer
from deid.spans import OcrDocument, PageSpans

log = logging.getLogger(__name__)


def ocr_document(
    engine: OcrEngine,
    source_path: str,
    config: Config,
    progress=None,
    index: int = 0,
) -> OcrDocument:
    """OCR every page or frame of one document."""
    progress = progress or NullProgress()
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
        doc, kind = open_document(source_path)
    except Exception as exc:
        log.error("open failed for %s: %s", source_path, exc)
        document.status = "error"
        document.error = str(exc)
        document.duration_seconds = round(time.perf_counter() - started, 2)
        return document

    # Announced before the first page so the UI can show "1 of 100"
    # rather than a bare spinner for the ~30s that page one takes.
    try:
        total_pages = page_count(doc, kind)
    except Exception:
        total_pages = 0
    progress.document(index, source_path, total_pages)

    try:
        for rendered in render_pages(doc, kind, config.dpi):
            spans = engine.read_page(rendered.image)
            document.pages.append(
                PageSpans(
                    page_number=rendered.page_number,
                    scale=rendered.scale,
                    spans=spans,
                )
            )
            progress.page(rendered.page_number)
    except Exception as exc:
        log.exception("OCR failed for %s", source_path)
        document.status = "error"
        document.error = str(exc)
    finally:
        close_document(doc, kind)

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
    """Process a batch."""
    engine = OcrEngine(config)
    outcomes: List[dict] = []

    # Every job in a batch carries the same progress file and the same
    # run-wide total; `index` is what moves. Both are absent unless the
    # caller asked for progress, in which case this is a no-op writer.
    first = jobs[0] if jobs else {}
    progress = progress_writer(
        first.get("progress"), file_total=int(first.get("file_total") or len(jobs) or 1)
    )

    for job in jobs:
        source = job["source"]
        document = ocr_document(
            engine, source, config, progress=progress, index=int(job.get("index", 0))
        )
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
