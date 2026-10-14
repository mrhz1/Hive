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


def configure_logging(level: int = logging.INFO) -> None:
    level = _configured_level(level)
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)

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
    """A short, stable stand-in for a file path or name in the logs.

    Sites name files and folders freely, so a path can hold a patient's
    name; the logs (readable by everyone on the project) get this instead.
    The same path always gives the same ref, so the lines about one file
    still connect, and anyone holding the path can compute it to search:
    `python -c "from app.logging_setup import ref; print(ref('AA1234/scan.pdf'))"`.
    """
    import hashlib

    return hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:12]
