"""Request correlation middleware.

Binds a request_id (honouring an inbound X-Request-ID if the caller sent
one, so ids survive across service hops) into structlog contextvars for
the lifetime of the request. Every log line emitted while handling that
request -- including background audit writes spawned from it -- carries
the same request_id, which is what makes an end to end trace greppable.
"""
import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware

from app.logging_setup import get_logger

log = get_logger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )

        log.info("request_started")
        started = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            # The exception handlers produce the response; log the timing
            # here so failed requests still get a duration line.
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            log.exception("request_errored", duration_ms=duration_ms)
            raise

        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        log.info(
            "request_finished",
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        response.headers["X-Request-ID"] = request_id
        return response
