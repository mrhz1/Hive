"""Hive connection handling, keyed off the same env vars Cloudera AI
provides at runtime (HIVE_HOST/PORT/DB/AUTH/USER). No environment
branching anywhere in the app -- only the values in .env.local vs. the
Cloudera AI runtime differ.
"""
import os
import time
from contextlib import contextmanager

from dotenv import load_dotenv
from impala.dbapi import connect

from app.errors import DatabaseError
from app.logging_setup import get_logger

load_dotenv(".env.local")

log = get_logger(__name__)

# Hive will not accept a bound parameter for a TIMESTAMP column -- neither
# a plain %s nor CAST(%s AS TIMESTAMP) lands a value. The only form that
# writes is the function itself, inlined into the statement text. So every
# timestamp this app stores comes from the Hive server's clock, not the
# app's, and is never a bound parameter.
NOW_SQL = "current_timestamp()"

# A nullable timestamp still needs its type stated -- Hive cannot tell what
# an untyped NULL is meant to be in a VALUES list.
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
    """Standalone cursor. Used by background tasks, which run after the
    request's own connection has already been closed."""
    conn = _connect()
    try:
        yield conn.cursor()
    finally:
        try:
            conn.close()
        except Exception as exc:  # pragma: no cover - close is best effort
            log.warning("hive_close_failed", error=str(exc))


def get_cursor():
    """FastAPI dependency. One connection per request, shared by the
    permission check and the route handler (FastAPI caches dependency
    results per request), so a request costs one Hive connection rather
    than one per query -- connection setup is not cheap here.
    """
    conn = _connect()
    try:
        yield conn.cursor()
    finally:
        try:
            conn.close()
        except Exception as exc:  # pragma: no cover - close is best effort
            log.warning("hive_close_failed", error=str(exc))


def execute(cursor, sql: str, params: tuple = ()):
    """Run a statement with timing + failure logging.

    Hive queries are slow enough that per query duration is worth having in
    the trace; this is also the single place raw impyla errors get turned
    into DatabaseError so no route leaks a thrift traceback.
    """
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
