"""structlog configuration.

Uses structlog.contextvars so anything bound in the request middleware
(request_id, actor, method, path) is automatically attached to every log
line emitted downstream -- CRUD, audit writes, background tasks -- without
threading a logger through call signatures. That is what makes an end to
end transaction traceable by grepping a single request_id.
"""
import logging
import sys

import structlog


def configure_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            # Console renderer is readable locally. Swap for
            # structlog.processors.JSONRenderer() if the Cloudera AI log
            # collector prefers JSON -- purely a config change.
            structlog.dev.ConsoleRenderer(colors=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str):
    return structlog.get_logger(name)
