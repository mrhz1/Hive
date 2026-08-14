"""Database connections, split across two engines.

Reads and inserts go to Impala, updates and deletes to Hive. That is the
division IT asked for, and it is not arbitrary: Impala is the fast query
engine, Hive is the one that owns the ACID tables and can rewrite rows
in them.

Both speak HiveServer2, so both are DB-API connections and callers see
one cursor either way. The routing is decided per *statement* rather
than per connection, because a single request routinely does both --
read the row, then update it -- and splitting at connection level would
mean every call site knowing which engine it wanted.

Hive is reached with our own impyla connection, keyed off the env vars
Cloudera AI provides (HIVE_HOST/PORT/DB/AUTH/USER). Impala is reached
through the platform's own data connection (`cml.data_v1`), which
carries host, port, TLS and Kerberos with it -- there is nothing to
configure here but its name. Where that module is absent, which is
anywhere outside a Cloudera workload, everything falls back to Hive and
the application behaves as it did before this split existed.
"""
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

HIVE = "hive"
IMPALA = "impala"

# The name of the Cloudera AI data connection that reaches Impala. Unset
# means there is no Impala to reach, and everything goes to Hive.
IMPALA_CONNECTION = (os.environ.get("CML_IMPALA_CONNECTION") or "").strip()

# What Impala runs. Everything else goes to Hive, which can run the lot:
# an unrecognised statement then fails on its own merits rather than for
# having been sent somewhere that was never going to accept it.
IMPALA_VERBS = frozenset(
    {
        "select",
        "with",
        "insert",
        "show",
        "describe",
        "explain",
        "refresh",
        "invalidate",
    }
)


def engine_for(sql: str) -> str:
    """Which engine runs this statement."""
    head = sql.lstrip().lstrip("(")
    verb = head.split(None, 1)[0].lower() if head else ""
    return IMPALA if verb in IMPALA_VERBS else HIVE


def impala_available() -> bool:
    """Whether an Impala connection could be opened at all.

    False on a laptop -- `cml.data_v1` only exists inside a Cloudera
    workload -- and false in any deployment that has not been given a
    connection name. Both cases route everything to Hive rather than
    failing, so local development needs no Impala and the tests do not
    know this module is here.
    """
    if not IMPALA_CONNECTION:
        return False
    try:
        import cml.data_v1  # noqa: F401
    except Exception:
        return False
    return True


def _hive_connection():
    """Our own connection, from the platform's env vars."""
    return connect(
        host=os.environ["HIVE_HOST"],
        port=int(os.environ["HIVE_PORT"]),
        database=os.environ["HIVE_DB"],
        auth_mechanism=os.environ["HIVE_AUTH"],
        user=os.environ["HIVE_USER"],
        # Kerberos needs the service half of the principal, which is
        # 'hive' for HiveServer2. Declared in .env all along and never
        # passed, which went unnoticed only because local auth is NOSASL.
        kerberos_service_name=os.environ.get("HIVE_SERVICE", "hive"),
    )


def _impala_connection():
    """The platform's handle, unwrapped to a plain DB-API connection.

    `get_base_connection()` is what makes the two engines
    interchangeable here: the same `.cursor()` and `.close()` as the
    Hive side, so nothing above this function knows which it has. The
    wrapper's own `get_pandas_dataframe` is deliberately not used --
    it takes a SQL string with no parameters, and every query in this
    application binds its values.
    """
    import cml.data_v1 as cmldata

    connection = cmldata.get_connection(IMPALA_CONNECTION)

    base = getattr(connection, "get_base_connection", None)
    if base is not None:
        opened = base()
        if hasattr(opened, "cursor"):
            return opened

    # Older wrappers hand out only a cursor. Present it as a connection
    # so the caller still has one shape to deal with.
    return _CursorOnly(connection)


class _CursorOnly:
    """A wrapper that only yields cursors, made to look like a connection."""

    def __init__(self, connection):
        self._connection = connection

    def cursor(self):
        return self._connection.get_cursor()

    def close(self):
        self._connection.close()


def _connect(engine: str):
    """Open one connection, or say clearly which engine would not open."""
    try:
        return _impala_connection() if engine == IMPALA else _hive_connection()
    except Exception as exc:
        log.error("db_connect_failed", engine=engine, error=str(exc))
        raise DatabaseError(f"Could not connect to {engine}: {exc}") from exc


class RoutingCursor:
    """One cursor to the caller, an engine's worth of connection behind each.

    Connections open on first use, so a request that only reads never
    opens a Hive session and a delete never opens an Impala one. The
    result methods delegate to whichever cursor ran the last statement:
    a fetchall() after a SELECT has to come from the connection that ran
    the SELECT.
    """

    # Class-level, so __getattr__ cannot recurse before __init__ has run.
    _last = None

    def __init__(self):
        self._connections: dict = {}
        self._cursors: dict = {}

    def cursor_for(self, engine: str):
        if engine not in self._cursors:
            connection = _connect(engine)
            self._connections[engine] = connection
            self._cursors[engine] = connection.cursor()
        return self._cursors[engine]

    def execute(self, sql, params=()):
        engine = engine_for(sql)
        if engine == IMPALA and not impala_available():
            engine = HIVE

        cursor = self.cursor_for(engine)
        self._last = cursor
        return cursor.execute(sql, params)

    def __getattr__(self, name):
        """fetchone / fetchall / description / rowcount, from the last engine used."""
        if self._last is None:
            raise DatabaseError(f"Nothing has been run, so '{name}' has no result")
        return getattr(self._last, name)

    def close(self):
        for engine, connection in self._connections.items():
            try:
                connection.close()
            except Exception as exc:  # pragma: no cover - close is best effort
                log.warning("db_close_failed", engine=engine, error=str(exc))


@contextmanager
def db_cursor():
    """Standalone cursor, for background threads and scripts."""
    cursor = RoutingCursor()
    try:
        yield cursor
    finally:
        cursor.close()


# The name every background caller already imports. Kept because it is
# patched by name in the tests, and because renaming thirteen call sites
# is not what this change is about.
hive_cursor = db_cursor


def get_cursor():
    """FastAPI dependency."""
    cursor = RoutingCursor()
    try:
        yield cursor
    finally:
        cursor.close()


def execute(cursor, sql: str, params: tuple = ()):
    """Run a statement with timing + failure logging."""
    started = time.perf_counter()
    try:
        cursor.execute(sql, params)
    except Exception as exc:
        log.error(
            "query_failed",
            engine=engine_for(sql),
            sql=" ".join(sql.split())[:200],
            error=str(exc),
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        raise DatabaseError(f"Query failed: {exc}") from exc

    log.debug(
        "query_ok",
        engine=engine_for(sql),
        sql=" ".join(sql.split())[:120],
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
    )
