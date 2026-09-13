import os
import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware

from app.errors import internal_error_response
from app.logging_setup import get_logger

log = get_logger(__name__)

MAX_USER_AGENT = 256


def _trusted_proxy_count() -> int:
    try:
        return max(0, int(os.environ.get("TRUSTED_PROXY_COUNT", "1")))
    except ValueError:
        return 1


def client_ip(request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        hops = [part.strip() for part in forwarded.split(",") if part.strip()]
        if hops:
            index = max(0, len(hops) - _trusted_proxy_count() - 1)
            return hops[index]

    client = getattr(request, "client", None)
    return getattr(client, "host", None) or "unknown"


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            source_ip=client_ip(request),
            user_agent=(request.headers.get("User-Agent") or "")[:MAX_USER_AGENT],
        )

        log.debug("request_started")
        started = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            log.exception("request_errored", duration_ms=duration_ms, error=str(exc))
            response = internal_error_response()

        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        log.info(
            "request_finished",
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        response.headers["X-Request-ID"] = request_id
        return response
