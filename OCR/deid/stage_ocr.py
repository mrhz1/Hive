import logging
import multiprocessing
import time
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Dict, List, Optional

from deid.config import Config, load_config
from deid.ocr_engine import OcrEngine
from deid.documents import (
    DICOM,
    PDF,
    close_document,
    kind_for,
    open_document,
    page_count,
    render_pages,
)
from deid.progress import NullProgress, writer as progress_writer
from deid.spans import OcrDocument, PageSpans

log = logging.getLogger(__name__)

_worker_engine: Optional[OcrEngine] = None
_worker_doc: Dict[str, Any] = {}


def _start_worker(cpu_threads: int) -> None:
    global _worker_engine
    config = load_config()
    config.cpu_threads = cpu_threads
    _worker_engine = OcrEngine(config)
    _worker_engine._load()


def _worker_document(source_path: str):
    if _worker_doc.get("source") != source_path:
        if "handle" in _worker_doc:
            _worker_doc.pop("handle").close()
        from deid.pdf_io import open_pdf

        _worker_doc["handle"] = open_pdf(source_path)
        _worker_doc["source"] = source_path
    return _worker_doc["handle"]


def _read_page(source_path: str, page_index: int, dpi: int) -> PageSpans:
    from deid.pdf_io import render_page

    rendered = render_page(_worker_document(source_path), page_index, dpi)
    return PageSpans(
        page_number=rendered.page_number,
        scale=rendered.scale,
        spans=_worker_engine.read_page(rendered.image),
    )


def _most_pages(jobs: List[Dict[str, Any]]) -> int:
    from deid.pdf_io import open_pdf

    most = 0
    for job in jobs:
        if kind_for(job["source"]) != PDF:
            continue
        try:
            with open_pdf(job["source"]) as doc:
                most = max(most, doc.page_count)
        except Exception:
            continue
    return most


def page_pool(config: Config, jobs: List[Dict[str, Any]]) -> Optional[ProcessPoolExecutor]:
    if config.page_workers <= 1:
        return None
    workers = min(config.page_workers, _most_pages(jobs))
    if workers <= 1:
        return None
    threads = max(1, config.cpu_threads // workers)
    log.info("ocr page pool: %d workers x %d threads", workers, threads)
    return ProcessPoolExecutor(
        max_workers=workers,
        mp_context=multiprocessing.get_context("spawn"),
        initializer=_start_worker,
        initargs=(threads,),
    )


def _pages_in_pool(pool, source_path: str, total_pages: int, dpi: int, progress):
    futures = [
        pool.submit(_read_page, source_path, index, dpi) for index in range(total_pages)
    ]
    try:
        for future in futures:
            page = future.result()
            progress.page(page.page_number)
            yield page
    finally:
        for future in futures:
            future.cancel()


def _pages_in_process(engine: OcrEngine, doc, kind: str, dpi: int, progress, only=None):
    for done, rendered in enumerate(render_pages(doc, kind, dpi, only), start=1):
        page = PageSpans(
            page_number=rendered.page_number,
            scale=rendered.scale,
            spans=engine.read_page(rendered.image),
        )
        progress.page(done)
        yield page


def ocr_document(
    engine: OcrEngine,
    source_path: str,
    config: Config,
    progress=None,
    index: int = 0,
    pool: Optional[ProcessPoolExecutor] = None,
) -> OcrDocument:
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

    try:
        total_pages = page_count(doc, kind)
    except Exception:
        total_pages = 0

    only = None
    if kind == DICOM:
        from deid.dicom_io import frames_to_ocr

        only = frames_to_ocr(total_pages, config.dicom_frame_ocr)
        document.total_frames = total_pages
        document.frame_mode = config.dicom_frame_ocr
        progress.document(index, source_path, len(only))
    else:
        progress.document(index, source_path, total_pages)

    try:
        if pool is not None and kind == PDF and total_pages > 1:
            pages = _pages_in_pool(pool, source_path, total_pages, config.dpi, progress)
        else:
            pages = _pages_in_process(engine, doc, kind, config.dpi, progress, only)
        for page in pages:
            document.pages.append(page)
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
    engine = OcrEngine(config)
    outcomes: List[dict] = []

    first = jobs[0] if jobs else {}
    progress = progress_writer(
        first.get("progress"), file_total=int(first.get("file_total") or len(jobs) or 1)
    )

    pool = page_pool(config, jobs)
    try:
        for job in jobs:
            source = job["source"]
            document = ocr_document(
                engine,
                source,
                config,
                progress=progress,
                index=int(job.get("index", 0)),
                pool=pool,
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
    finally:
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)

    return outcomes
