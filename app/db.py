"""Database connections, split across two engines.

Queries go to Impala; everything that writes goes to Hive. That is the
division IT asked for, and it follows from what the two engines can do:
Impala is the fast query engine, and Hive owns these tables -- they are
full-ACID ORC, which Impala reads but will not write.

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
import re
import threading
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

# Which database a fresh Impala session should point at. The data
# connection does not carry one -- unlike the Hive connection, which
# takes it as a parameter -- so without this an unqualified `users`
# resolves against `default`. The tables are not there, and Impala
# reports that as a privilege error rather than a missing table, which
# sends you looking for a grant that was never the problem.
IMPALA_DB = (os.environ.get("IMPALA_DB") or os.environ.get("HIVE_DB") or "").strip()

# A database name goes into the statement as an identifier, and an
# identifier cannot be bound as a parameter. Since it comes from the
# environment, it is checked rather than trusted.
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Whether to tell Impala about a table Hive has just written to. On by
# default: without it the engine that answers every read carries on
# serving what the table looked like before the write.
REFRESH_AFTER_WRITE = (
    os.environ.get("IMPALA_REFRESH_AFTER_WRITE", "true") or ""
).strip().lower() not in ("0", "false", "no", "off")

# The table a write lands on. Only has to understand the statements this
# codebase generates, which are all of the form `INSERT INTO x`,
# `INSERT INTO TABLE x`, `UPDATE x`, `DELETE FROM x` or `MERGE INTO x`.
_WRITTEN_TABLE = re.compile(
    r"^\s*(?:INSERT\s+(?:INTO|OVERWRITE)\s+(?:TABLE\s+)?"
    r"|UPDATE\s+|DELETE\s+FROM\s+|MERGE\s+INTO\s+)"
    r"`?([A-Za-z_][A-Za-z0-9_]*(?:`?\.`?[A-Za-z_][A-Za-z0-9_]*)?)`?",
    re.IGNORECASE,
)


def written_table(sql: str) -> str:
    """The table a write statement modifies, or '' if it is not a write."""
    found = _WRITTEN_TABLE.match(sql or "")
    return found.group(1) if found else ""

# What Impala runs: queries, and nothing else.
#
# Not inserts. Every table here is full-ACID ORC, and Impala will not
# write to those -- it reads them and refuses to modify them. So all
# writing, inserts included, stays with Hive, which owns those tables.
#
# `with` is in the list because a CTE is still a query: it begins with
# WITH and ends in a SELECT.
IMPALA_VERBS = frozenset({"select", "with"})


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


# Whether to keep an Impala connection open between requests.
IMPALA_POOL = (os.environ.get("IMPALA_POOL", "true") or "").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)

_pool = threading.local()


def _impala_session():
    """The calling thread's Impala cursor, opened once and kept.

    Authenticating is not cheap -- a Kerberos handshake per connection --
    and one page is several requests, so opening a connection for each
    meant several authentications in a row to fill one table. That is
    what the repeated 'using kerberos authentication' in the log was, and
    most of the wait with it.

    Parked on the thread rather than shared: FastAPI hands each request
    to a thread from its pool and a thread serves one request at a time,
    so a connection kept here is never used by two requests at once --
    which a DB-API connection would not survive.

    Only Impala is pooled. Everything it runs is a read, so a session
    found dead can be reopened and the query simply run again. The same
    is not true of a write: a statement that reached the server before
    the connection dropped would be applied a second time by the retry.

    Returns the cursor and whether it was already open, because only a
    reused session is worth retrying.
    """
    session = getattr(_pool, "impala", None)
    if session is not None:
        return session[1], True

    connection = _connect(IMPALA)
    cursor = connection.cursor()
    use_database(cursor, IMPALA_DB)

    _pool.impala = (connection, cursor)
    log.debug("impala_session_opened")
    return cursor, False


def discard_impala_session() -> None:
    """Drop the thread's Impala session; the next use opens a fresh one."""
    session = getattr(_pool, "impala", None)
    _pool.impala = None

    if session is None:
        return
    try:
        session[0].close()
    except Exception as exc:  # pragma: no cover - closing a dead session
        log.debug("impala_session_close_failed", error=str(exc))


def use_database(cursor, database: str) -> None:
    """Point a fresh session at the database the tables are actually in.

    Run on the raw cursor rather than through the router: `USE` is a
    session setting, so it has to land on this connection and not be
    dispatched somewhere by its verb.
    """
    if not database:
        return

    if not _IDENTIFIER.match(database):
        raise DatabaseError(
            f"'{database}' is not a usable database name "
            "(set IMPALA_DB or HIVE_DB to a plain identifier)"
        )

    cursor.execute(f"USE `{database}`")


class RoutingCursor:
    """One cursor to the caller, an engine's worth of connection behind each.

    Connections open on first use, so a request that only reads never
    opens a Hive session and a delete never opens an Impala one. The
    result methods delegate to whichever cursor ran the last statement:
    a fetchall() after a SELECT has to come from the connection that ran
    the SELECT.
    """

    # Class-level, so __getattr__ cannot recurse before __init__ has run,
    # and so reading either of them never falls through to a cursor.
    _last = None
    force_hive = False

    def __init__(self):
        self._connections: dict = {}
        self._cursors: dict = {}
        self._written: set = set()
        self._reused_impala = False

    def cursor_for(self, engine: str):
        if engine in self._cursors:
            return self._cursors[engine]

        if engine == IMPALA and IMPALA_POOL:
            # Borrowed from the thread, not opened. Deliberately not
            # recorded in _connections: closing this request must leave
            # the session open for the next one.
            cursor, self._reused_impala = _impala_session()
            self._cursors[engine] = cursor
            return cursor

        connection = _connect(engine)
        self._connections[engine] = connection

        cursor = connection.cursor()
        # Hive takes the database as a connection parameter; Impala's
        # data connection has nowhere to put one, so its session is
        # pointed at the right database here.
        if engine == IMPALA:
            use_database(cursor, IMPALA_DB)

        self._cursors[engine] = cursor
        return cursor

    def execute(self, sql, params=()):
        engine = engine_for(sql)

        if engine == IMPALA and not impala_available():
            engine = HIVE
        elif engine == IMPALA and self.force_hive:
            # Asked for on the miss path, where a stale answer would be
            # reported to the caller as 'no such thing'.
            engine = HIVE
        elif engine == IMPALA and self._written:
            # Read back what this request has already written, from the
            # engine that wrote it. Impala is not told about a Hive write
            # until it is refreshed, so a row inserted a millisecond ago
            # is simply not there yet -- which is how creating a patient
            # came back as 'patient not found' from the same call that
            # had just created them.
            engine = HIVE

        cursor = self.cursor_for(engine)
        self._last = cursor

        table = written_table(sql)
        if table:
            self._written.add(table)

        try:
            return cursor.execute(sql, params)
        except Exception as exc:
            if not (engine == IMPALA and IMPALA_POOL and self._reused_impala):
                raise

            # A session parked between requests can be closed from the
            # other end -- an idle timeout, a restarted daemon, a Kerberos
            # ticket that has run out. Reopening and asking again is safe
            # here and nowhere else: Impala only ever runs reads, so at
            # worst the query is answered twice.
            log.info("impala_session_retry", error=str(exc))
            discard_impala_session()
            self._cursors.pop(IMPALA, None)

            cursor = self.cursor_for(IMPALA)
            self._last = cursor
            return cursor.execute(sql, params)

    def _refresh_written(self) -> None:
        """Tell Impala about the tables this request wrote.

        At the end rather than after each statement, so a request that
        writes five rows to one table refreshes it once. Failing to
        refresh must not fail the request -- the write itself already
        succeeded, and the cost of a miss is a stale read, not a lost
        row.
        """
        if not self._written or not REFRESH_AFTER_WRITE:
            return
        if not impala_available():
            return

        try:
            cursor = self.cursor_for(IMPALA)
        except DatabaseError as exc:
            log.warning("impala_refresh_unreachable", error=str(exc))
            return

        for table in sorted(self._written):
            try:
                cursor.execute(f"REFRESH {table}")
            except Exception as exc:
                log.warning("impala_refresh_failed", table=table, error=str(exc))

    def __getattr__(self, name):
        """fetchone / fetchall / description / rowcount, from the last engine used."""
        if self._last is None:
            raise DatabaseError(f"Nothing has been run, so '{name}' has no result")
        return getattr(self._last, name)

    def close(self):
        self._refresh_written()

        for engine, connection in self._connections.items():
            try:
                connection.close()
            except Exception as exc:  # pragma: no cover - close is best effort
                log.warning("db_close_failed", engine=engine, error=str(exc))


@contextmanager
def authoritative(cursor):
    """Read from the engine that owns the rows, for the duration.

    Impala learns of a Hive write only when it is refreshed, and a
    refresh does not reach every coordinator the same instant. So a row
    written moments ago in an earlier request can be missing from a query
    that is otherwise perfectly correct -- which is how creating a
    patient and immediately filing an application against them came back
    as 'patient not found' for a patient that plainly existed.

    Used on the miss path, not the happy one: a row that was found needs
    no second opinion, and a row that was not is worth one before anybody
    is told it does not exist.
    """
    previous = getattr(cursor, "force_hive", False)
    try:
        cursor.force_hive = True
    except AttributeError:  # pragma: no cover - a cursor that does not route
        yield
        return

    try:
        yield
    finally:
        cursor.force_hive = previous


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
