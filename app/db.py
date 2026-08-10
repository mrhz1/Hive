"""Hive connection handling, keyed off the same env vars Cloudera AI provides at runtime (HIVE_HOST/PORT/DB/AUTH/USER)."""
import os
import time
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv
from impala.dbapi import connect

from app.errors import DatabaseError
from app.logging_setup import get_logger

load_dotenv(Path(__file__).resolve().parent.parent / ".env.local")

log = get_logger(__name__)

NOW_SQL = "current_timestamp()"

NULL_TIMESTAMP_SQL = "CAST(NULL AS TIMESTAMP)"


def _connect():
    try:
        return connect(
            host=os.environ["HIVE_HOST"],
            port=int(os.environ["HIVE_PORT"]),
            database=os.environ["HIVE_DB"],
            auth_mechanism=os.environ["HIVE_AUTH"],
            user=os.environ["HIVE_USER"],
        )
    except Exception as exc:
        log.error("hive_connect_failed", error=str(exc))
        raise DatabaseError(f"Could not connect to Hive: {exc}") from exc


@contextmanager
def hive_cursor():
    """Standalone cursor."""
    conn = _connect()
    try:
        yield conn.cursor()
    finally:
        try:
            conn.close()
        except Exception as exc:  # pragma: no cover - close is best effort
            log.warning("hive_close_failed", error=str(exc))


def get_cursor():
    """FastAPI dependency."""
    conn = _connect()
    try:
        yield conn.cursor()
    finally:
        try:
            conn.close()
        except Exception as exc:  # pragma: no cover - close is best effort
            log.warning("hive_close_failed", error=str(exc))


def execute(cursor, sql: str, params: tuple = ()):
    """Run a statement with timing + failure logging."""
    started = time.perf_counter()
    try:
        cursor.execute(sql, params)
    except Exception as exc:
        log.error(
            "query_failed",
            sql=" ".join(sql.split())[:200],
            error=str(exc),
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        raise DatabaseError(f"Query failed: {exc}") from exc

    log.debug(
        "query_ok",
        sql=" ".join(sql.split())[:120],
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
    )
