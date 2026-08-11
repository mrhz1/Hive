"""structlog configuration.

Two renderings of the same events:

- **console** -- aligned key=value, for a terminal. What you want while
  working, and unreadable to a machine.
- **json** -- one object per line, for anything that ingests logs. What
  you want in production, and tiring to read by eye.

Which one is picked automatically: a terminal gets console, a pipe gets
json, because in production stdout is captured rather than watched.
`LOG_FORMAT` overrides it either way.
"""
import logging
import os
import sys

import structlog

VALID_FORMATS = ("console", "json")


def _configured_format() -> str:
    """'console' or 'json' -- explicit if set, otherwise by where stdout goes."""
    chosen = (os.environ.get("LOG_FORMAT") or "").strip().lower()
    if chosen in VALID_FORMATS:
        return chosen

    # A TTY means somebody is reading it; anything else is being captured.
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
        # ConsoleRenderer formats exceptions itself and warns if this has
        # already flattened them, so it is only wanted on the JSON path.
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
