import json
import logging
import multiprocessing
import threading
import time
from concurrent.futures import CancelledError, ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from functools import partial
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


def _read_frames(source_path: str, dpi: int, only) -> List[PageSpans]:
    doc, kind = open_document(source_path)
    try:
        return [
            PageSpans(
                page_number=rendered.page_number,
                scale=rendered.scale,
                spans=_worker_engine.read_page(rendered.image),
            )
            for rendered in render_pages(doc, kind, dpi, only)
        ]
    finally:
        close_document(doc, kind)


def _timed(call, *args):
    started = time.perf_counter()
    return call(*args), time.perf_counter() - started


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


WORKER_STOPPED = "an OCR worker stopped, most likely out of memory"


class _Served:
    def __init__(self, job: Dict[str, Any], document: OcrDocument, progress):
        self.job = job
        self.document = document
        self.progress = progress
        self.started = time.perf_counter()
        self.seconds = 0.0
        self.futures = []
        self.waiting = 0
        self.error = None
        self.retry = False
        self.lock = threading.Lock()


class PageServer:
    def __init__(self, config: Config, out):
        self.config = config
        self.out = out
        self.out_lock = threading.Lock()
        self.workers = max(1, config.page_workers)
        self.threads = max(1, config.cpu_threads // self.workers)
        self.pool = None
        self.pool_lock = threading.Lock()
        self.running = 0
        self.idle = threading.Condition()

    def _get_pool(self) -> ProcessPoolExecutor:
        with self.pool_lock:
            if self.pool is None:
                log.info("ocr page pool: %d workers x %d threads", self.workers, self.threads)
                self.pool = ProcessPoolExecutor(
                    max_workers=self.workers,
                    mp_context=multiprocessing.get_context("spawn"),
                    initializer=_start_worker,
                    initargs=(self.threads,),
                )
            return self.pool

    def _drop_pool(self, pool) -> None:
        with self.pool_lock:
            if self.pool is pool:
                self.pool = None

    def _submit(self, call, *args):
        for _ in range(2):
            pool = self._get_pool()
            try:
                return pool, pool.submit(call, *args)
            except BrokenProcessPool:
                self._drop_pool(pool)
        raise BrokenProcessPool(WORKER_STOPPED)

    def submit(self, job: Dict[str, Any]) -> None:
        source = job["source"]
        document = OcrDocument(
            source_path=source,
            dpi=self.config.dpi,
            models={
                "detection": self.config.det_model,
                "recognition": self.config.rec_model,
            },
        )
        served = _Served(job, document, progress_writer(job.get("progress"), file_total=1))
        with self.idle:
            self.running += 1

        try:
            doc, kind = open_document(source)
        except Exception as exc:
            log.error("open failed for %s: %s", source, exc)
            served.error = str(exc)
            self._finish(served)
            return
        try:
            total_pages = page_count(doc, kind)
        except Exception:
            total_pages = 0
        finally:
            close_document(doc, kind)

        if kind == DICOM:
            from deid.dicom_io import frames_to_ocr

            only = frames_to_ocr(total_pages, self.config.dicom_frame_ocr)
            document.total_frames = total_pages
            document.frame_mode = self.config.dicom_frame_ocr
            served.progress.document(0, source, len(only))
            calls = [(_timed, _read_frames, source, self.config.dpi, only)]
        else:
            served.progress.document(0, source, total_pages)
            calls = [
                (_timed, _read_page, source, index, self.config.dpi)
                for index in range(total_pages)
            ]

        if not calls:
            self._finish(served)
            return

        with served.lock:
            served.waiting = len(calls)
        for number, (call, *args) in enumerate(calls):
            try:
                pool, future = self._submit(call, *args)
            except BrokenProcessPool:
                with served.lock:
                    served.error = served.error or WORKER_STOPPED
                    served.retry = True
                    served.waiting -= len(calls) - number
                    last = served.waiting == 0
                if last:
                    self._finish(served)
                return
            with served.lock:
                served.futures.append(future)
            future.add_done_callback(partial(self._page_done, served, pool))

    def _page_done(self, served: _Served, pool, future) -> None:
        found = []
        seconds = 0.0
        error = None
        retry = False
        try:
            result, seconds = future.result()
            found = result if isinstance(result, list) else [result]
        except CancelledError:
            error = "cancelled"
        except BrokenProcessPool:
            self._drop_pool(pool)
            error = WORKER_STOPPED
            retry = True
        except Exception as exc:
            log.error("OCR failed for %s: %s", served.job["source"], exc)
            error = str(exc)

        to_cancel = []
        with served.lock:
            served.seconds += seconds
            if error is None:
                served.document.pages.extend(found)
                served.progress.page(len(served.document.pages))
            elif served.error is None:
                served.error = error
                served.retry = retry
                to_cancel = list(served.futures)
            served.waiting -= 1
            last = served.waiting == 0
        for other in to_cancel:
            other.cancel()
        if last:
            self._finish(served)

    def _finish(self, served: _Served) -> None:
        document = served.document
        document.pages.sort(key=lambda page: page.page_number)
        if served.error:
            document.status = "error"
            document.error = served.error
        if served.futures:
            document.duration_seconds = round(served.seconds, 2)
        else:
            document.duration_seconds = round(time.perf_counter() - served.started, 2)
        job = served.job
        try:
            document.write(job["spans"])
        except Exception as exc:
            log.exception("could not write OCR handoff for %s", job["source"])
            document.status = "error"
            document.error = f"could not write OCR handoff: {exc}"
        log.info(
            "ocr %s | pages=%d spans=%d %.2fs [%s]",
            job["source"],
            len(document.pages),
            document.total_spans,
            document.duration_seconds,
            document.status,
        )
        outcome = {
            "id": job.get("id"),
            "source": job["source"],
            "spans": job["spans"],
            "status": document.status,
            "error": document.error,
            "retry": served.retry,
            "pages": len(document.pages),
            "spans_found": document.total_spans,
            "duration_seconds": document.duration_seconds,
        }
        with self.out_lock:
            self.out.write(json.dumps(outcome) + "\n")
            self.out.flush()
        with self.idle:
            self.running -= 1
            self.idle.notify_all()

    def wait(self) -> None:
        with self.idle:
            while self.running:
                self.idle.wait()

    def close(self) -> None:
        with self.pool_lock:
            pool, self.pool = self.pool, None
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)


def serve(config: Config, lines, out) -> None:
    server = PageServer(config, out)
    try:
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                job = json.loads(line)
            except ValueError:
                log.error("ignoring a request that is not JSON")
                continue
            server.submit(job)
        server.wait()
    finally:
        server.close()
