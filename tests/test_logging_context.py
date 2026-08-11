"""What every log line carries, and what it must never carry.

'Which account' is not enough to scope an incident or spot a shared
login, so the request's origin is bound once here rather than passed by
every call site.
"""
import json
import logging
import sys

import pytest
import structlog

from app import deid
from app.logging_setup import _configured_format, configure_logging
from app.middleware import client_ip


class _Request:
    """Enough of a Starlette request for the address logic."""

    def __init__(self, headers=None, host="127.0.0.1"):
        self.headers = headers or {}
        self.client = type("Client", (), {"host": host})()


# ------------------------------------------------------------ the caller


def test_the_socket_address_is_used_when_nothing_is_in_front(monkeypatch):
    monkeypatch.delenv("TRUSTED_PROXY_COUNT", raising=False)

    assert client_ip(_Request(host="10.1.2.3")) == "10.1.2.3"


def test_the_caller_is_read_from_behind_one_proxy(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_COUNT", "1")

    request = _Request({"X-Forwarded-For": "203.0.113.9, 10.0.0.1"})

    assert client_ip(request) == "203.0.113.9"


def test_the_caller_is_read_from_behind_two_proxies(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_COUNT", "2")

    request = _Request({"X-Forwarded-For": "203.0.113.9, 10.0.0.1, 10.0.0.2"})

    assert client_ip(request) == "203.0.113.9"


def test_a_short_header_does_not_read_off_the_end(monkeypatch):
    """A direct hit that skipped the proxy still has to resolve to
    something rather than raising."""
    monkeypatch.setenv("TRUSTED_PROXY_COUNT", "2")

    assert client_ip(_Request({"X-Forwarded-For": "203.0.113.9"})) == "203.0.113.9"


def test_a_client_with_no_address_at_all_is_named_not_blank():
    request = _Request()
    request.client = None

    assert client_ip(request) == "unknown"


def test_an_unparseable_proxy_count_falls_back(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_COUNT", "not a number")

    request = _Request({"X-Forwarded-For": "203.0.113.9, 10.0.0.1"})

    assert client_ip(request) == "203.0.113.9"


# ------------------------------------------------- through a real request


def test_every_line_of_a_request_carries_its_origin(as_admin, caplog):
    """Bound once in the middleware, so a later access record does not
    depend on each call site remembering."""
    with caplog.at_level(logging.INFO):
        as_admin.get(
            "/patients",
            headers={"X-Forwarded-For": "203.0.113.9", "User-Agent": "Firefox/1"},
        )

    finished = [r for r in caplog.records if "request_finished" in r.getMessage()]
    assert finished, "the request should have been logged"

    message = finished[-1].getMessage()
    assert "203.0.113.9" in message
    assert "Firefox/1" in message
    assert "request_id" in message


def test_a_long_user_agent_is_truncated(as_admin, caplog):
    with caplog.at_level(logging.INFO):
        as_admin.get("/patients", headers={"User-Agent": "A" * 4000})

    message = [
        r.getMessage() for r in caplog.records if "request_finished" in r.getMessage()
    ][-1]

    assert "A" * 300 not in message


# ----------------------------------------------------------- the renderer


@pytest.mark.parametrize(
    "value,expected", [("json", "json"), ("console", "console"), ("JSON", "json")]
)
def test_the_format_can_be_set_explicitly(monkeypatch, value, expected):
    monkeypatch.setenv("LOG_FORMAT", value)

    assert _configured_format() == expected


def test_a_pipe_gets_json_and_a_terminal_gets_console(monkeypatch):
    """In production stdout is captured, not watched."""
    monkeypatch.delenv("LOG_FORMAT", raising=False)

    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    assert _configured_format() == "json"

    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    assert _configured_format() == "console"


def test_an_unknown_format_does_not_break_startup(monkeypatch):
    monkeypatch.setenv("LOG_FORMAT", "yaml-please")
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)

    assert _configured_format() == "json"


@pytest.fixture
def json_logging(monkeypatch):
    """Render as JSON for one test, then put the config back.

    structlog's configuration is global, so leaving it set would change
    how every later test logs.
    """
    monkeypatch.setenv("LOG_FORMAT", "json")
    configure_logging()
    yield
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    configure_logging()


def _rendered(caplog):
    """The line as it was handed to stdout -- the JSON, not the fields."""
    return caplog.records[-1].getMessage()


def test_json_output_is_one_parseable_object_per_line(json_logging, caplog):
    with caplog.at_level(logging.INFO):
        structlog.get_logger("test").info("access_download", patient_id="A7K2P9")

    parsed = json.loads(_rendered(caplog))

    assert parsed["event"] == "access_download"
    assert parsed["patient_id"] == "A7K2P9"
    assert parsed["level"] == "info"
    assert parsed["timestamp"].endswith("Z")


def test_json_output_carries_the_traceback(json_logging, caplog):
    with caplog.at_level(logging.INFO):
        try:
            raise RuntimeError("hive is down")
        except RuntimeError:
            structlog.get_logger("test").exception("unhandled_exception")

    parsed = json.loads(_rendered(caplog))

    assert "RuntimeError" in parsed["exception"]
    assert "hive is down" in parsed["exception"]


# -------------------------------------------------------- PHI in the logs


def test_a_failed_deid_run_does_not_log_the_document(caplog):
    """The NLP stage's dependencies quote the document into their
    warnings, so forwarding a failed run's output wholesale would
    re-leak exactly what the pipeline removes."""
    leaky = (
        "UserWarning: Skipping annotation for doc "
        "'Patient Jane Doe, MRN 4471, seen on 3 March'\n"
        "ERROR: stage failed with code 2\n"
    )

    detail = deid._failure_detail(leaky, "")

    assert "ERROR: stage failed with code 2" in detail
    assert "Jane Doe" not in detail
    assert "MRN 4471" not in detail


def test_the_whole_output_is_kept_when_there_is_no_error_line():
    """Something has to be reported, but never more than a bounded
    amount of it."""
    detail = deid._failure_detail("x" * 5000, "")

    assert len(detail) <= 500
