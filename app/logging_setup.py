import logging
import os
import sys

import structlog

VALID_FORMATS = ("console", "json")


def _configured_format() -> str:
    chosen = (os.environ.get("LOG_FORMAT") or "").strip().lower()
    if chosen in VALID_FORMATS:
        return chosen

    return "console" if sys.stdout.isatty() else "json"


def _configured_level(default: int) -> int:
    name = (os.environ.get("LOG_LEVEL") or "").strip().upper()
    if not name:
        return default
    return getattr(logging, name, default)


class _HideHealthChecks(logging.Filter):
    """Uvicorn's access line for Cloudera's health check (GET / every second)."""

    def filter(self, record):
        args = record.args if isinstance(record.args, tuple) else ()
        if len(args) >= 5:  # (client, method, path, http version, status)
            path, status = str(args[2]).split("?")[0], args[4]
            if path in ("/", "/health") and isinstance(status, int) and status < 400:
                return False
        return True


def configure_logging(level: int = logging.INFO) -> None:
    level = _configured_level(level)
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, _HideHealthChecks) for f in access.filters):
        access.addFilter(_HideHealthChecks())

    log_format = _configured_format()

    shared = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    if log_format == "json":
        renderers = [
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ]
    else:
        renderers = [
            structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty()),
        ]

    structlog.configure(
        processors=shared + renderers,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str):
    return structlog.get_logger(name)


def ref(path) -> str:
    import hashlib

    return hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:12]
