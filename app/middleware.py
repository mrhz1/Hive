"""Request correlation middleware.

Binds the facts every log line in a request needs, so no call site has to
pass them: the correlation id, and who the request came from. The second
half is what makes an access record answerable later -- "which account"
is not enough on its own to scope an incident or spot a shared login.
"""
import os
import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware

from app.errors import internal_error_response
from app.logging_setup import get_logger

log = get_logger(__name__)

# A user agent is attacker-controlled and can be arbitrarily long.
MAX_USER_AGENT = 256


def _trusted_proxy_count() -> int:
    """How many reverse proxies sit in front of this app.

    On Cloudera AI there is at least one, which is also what terminates
    authentication and sets REMOTE-USER. Locally there is none, and
    X-Forwarded-For is absent, so the socket address is used instead.
    """
    try:
        return max(0, int(os.environ.get("TRUSTED_PROXY_COUNT", "1")))
    except ValueError:
        return 1


def client_ip(request) -> str:
    """The caller's address, as far as the proxies in front can be trusted.

    X-Forwarded-For reads client, proxy1, ..., proxyN with the nearest
    proxy last, so the caller is N entries from the right. Anything
    further left was appended by something upstream we do not control and
    a client can put whatever it likes there -- which is exactly why the
    count has to match the deployment rather than being guessed.
    """
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

        # Debug rather than info: it carries nothing request_finished does
        # not, and at two lines per request it is most of the log volume.
        log.debug("request_started")
        started = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            log.exception("request_errored", duration_ms=duration_ms, error=str(exc))
            # Answered here rather than re-raised. Starlette handles a
            # re-raised exception *outside* the CORS middleware, so the
            # 500 goes back with no Access-Control-Allow-Origin on it and
            # the browser reports a CORS failure -- hiding the actual
            # error behind a misconfiguration that isn't there. This
            # response passes back out through CORS like any other.
            response = internal_error_response()

        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        log.info(
            "request_finished",
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        response.headers["X-Request-ID"] = request_id
        return response
