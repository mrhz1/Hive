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

IMPALA_CONNECTION = (os.environ.get("CML_IMPALA_CONNECTION") or "").strip()


def _read_engine() -> str:
    configured = (os.environ.get("READ_ENGINE") or IMPALA).strip().lower()
    if configured in (IMPALA, HIVE):
        return configured

    log.error(
        "read_engine_unknown",
        configured=configured,
        detail=f"expected '{IMPALA}' or '{HIVE}'; falling back to {HIVE}",
    )
    return HIVE


READ_ENGINE = _read_engine()

IMPALA_DB = (os.environ.get("IMPALA_DB") or os.environ.get("HIVE_DB") or "").strip()

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

REFRESH_AFTER_WRITE = (
    os.environ.get("IMPALA_REFRESH_AFTER_WRITE", "true") or ""
).strip().lower() not in ("0", "false", "no", "off")

_WRITTEN_TABLE = re.compile(
    r"^\s*(?:INSERT\s+(?:INTO|OVERWRITE)\s+(?:TABLE\s+)?"
    r"|UPDATE\s+|DELETE\s+FROM\s+|MERGE\s+INTO\s+)"
    r"`?([A-Za-z_][A-Za-z0-9_]*(?:`?\.`?[A-Za-z_][A-Za-z0-9_]*)?)`?",
    re.IGNORECASE,
)


def written_table(sql: str) -> str:
    found = _WRITTEN_TABLE.match(sql or "")
    return found.group(1) if found else ""

IMPALA_VERBS = frozenset({"select", "with"})


def engine_for(sql: str) -> str:
    head = sql.lstrip().lstrip("(")
    verb = head.split(None, 1)[0].lower() if head else ""
    return IMPALA if verb in IMPALA_VERBS else HIVE


def impala_available() -> bool:
    if READ_ENGINE != IMPALA:
        return False
    if not IMPALA_CONNECTION:
        return False
    try:
        import cml.data_v1  # noqa: F401
    except Exception:
        return False
    return True


def _hive_connection():
    return connect(
        host=os.environ["HIVE_HOST"],
        port=int(os.environ["HIVE_PORT"]),
        database=os.environ["HIVE_DB"],
        auth_mechanism=os.environ["HIVE_AUTH"],
        user=os.environ["HIVE_USER"],
        kerberos_service_name=os.environ.get("HIVE_SERVICE", "hive"),
    )


def _impala_connection():
    import cml.data_v1 as cmldata

    connection = cmldata.get_connection(IMPALA_CONNECTION)

    base = getattr(connection, "get_base_connection", None)
    if base is not None:
        opened = base()
        if hasattr(opened, "cursor"):
            return opened

    return _CursorOnly(connection)


class _CursorOnly:

    def __init__(self, connection):
        self._connection = connection

    def cursor(self):
        return self._connection.get_cursor()

    def close(self):
        self._connection.close()


def _connect(engine: str):
    try:
        return _impala_connection() if engine == IMPALA else _hive_connection()
    except Exception as exc:
        log.error("db_connect_failed", engine=engine, error=str(exc))
        raise DatabaseError(f"Could not connect to {engine}: {exc}") from exc


def _flag(name: str, default: str = "true") -> bool:
    return (os.environ.get(name, default) or "").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


IMPALA_POOL = _flag("IMPALA_POOL")
HIVE_POOL = _flag("HIVE_POOL")

POOL_MAX_IDLE_SECONDS = float(os.environ.get("POOL_MAX_IDLE_SECONDS", "300"))

POOL_MAX_IDLE = int(os.environ.get("POOL_MAX_IDLE", "8"))

_idle: dict = {}
_pool_lock = threading.Lock()


def _pooled(engine: str) -> bool:
    return IMPALA_POOL if engine == IMPALA else HIVE_POOL


def _close_session(engine: str, connection) -> None:
    try:
        connection.close()
    except Exception as exc:  # pragma: no cover - closing a dead session
        log.debug("db_session_close_failed", engine=engine, error=str(exc))


def _open_session(engine: str):
    connection = _connect(engine)
    cursor = connection.cursor()
    if engine == IMPALA:
        use_database(cursor, IMPALA_DB)

    log.debug("db_session_opened", engine=engine)
    return connection, cursor


def _checkout(engine: str):
    while True:
        with _pool_lock:
            parked = _idle.get(engine)
            if not parked:
                break
            connection, cursor, parked_at = parked.pop()

        if time.monotonic() - parked_at <= POOL_MAX_IDLE_SECONDS:
            return connection, cursor, True

        log.debug("db_session_expired", engine=engine)
        _close_session(engine, connection)

    connection, cursor = _open_session(engine)
    return connection, cursor, False


def _checkin(engine: str, connection, cursor) -> None:
    with _pool_lock:
        parked = _idle.setdefault(engine, [])
        if len(parked) < POOL_MAX_IDLE:
            parked.append((connection, cursor, time.monotonic()))
            return

    _close_session(engine, connection)


def discard_session(engine: str) -> None:
    with _pool_lock:
        parked = _idle.pop(engine, [])

    for connection, _cursor, _parked_at in parked:
        _close_session(engine, connection)


def discard_impala_session() -> None:
    discard_session(IMPALA)


def discard_sessions() -> None:
    with _pool_lock:
        engines = list(_idle)

    for engine in engines:
        discard_session(engine)


def use_database(cursor, database: str) -> None:
    if not database:
        return

    if not _IDENTIFIER.match(database):
        raise DatabaseError(
            f"'{database}' is not a usable database name "
            "(set IMPALA_DB or HIVE_DB to a plain identifier)"
        )

    cursor.execute(f"USE `{database}`")


class RoutingCursor:

    _last = None
    force_hive = False

    def __init__(self):
        self._connections: dict = {}
        self._cursors: dict = {}
        self._written: set = set()
        self._reused: dict = {}
        self._pooled_engines: set = set()

    def cursor_for(self, engine: str):
        if engine in self._cursors:
            return self._cursors[engine]

        if _pooled(engine):
            connection, cursor, reused = _checkout(engine)
            self._reused[engine] = reused
            self._pooled_engines.add(engine)
        else:
            connection, cursor = _open_session(engine)

        self._connections[engine] = connection
        self._cursors[engine] = cursor
        return cursor

    def execute(self, sql, params=()):
        engine = engine_for(sql)

        if engine == IMPALA and not impala_available():
            engine = HIVE
        elif engine == IMPALA and self.force_hive:
            engine = HIVE
        elif engine == IMPALA and self._written:
            engine = HIVE

        cursor = self.cursor_for(engine)
        self._last = cursor

        table = written_table(sql)
        if table:
            self._written.add(table)

        try:
            return cursor.execute(sql, params)
        except Exception as exc:
            reused = engine in self._pooled_engines and self._reused.get(engine)
            if not reused:
                raise

            log.info("db_session_dropped", engine=engine, error=str(exc))
            _close_session(engine, self._connections.pop(engine))
            self._cursors.pop(engine, None)
            self._pooled_engines.discard(engine)
            self._reused.pop(engine, None)

            if engine != IMPALA:
                raise

            cursor = self.cursor_for(IMPALA)
            self._last = cursor
            return cursor.execute(sql, params)

    def _refresh_written(self) -> None:
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
        if self._last is None:
            raise DatabaseError(f"Nothing has been run, so '{name}' has no result")
        return getattr(self._last, name)

    def close(self):
        self._refresh_written()

        for engine, connection in self._connections.items():
            if engine in self._pooled_engines:
                _checkin(engine, connection, self._cursors.get(engine))
                continue
            try:
                connection.close()
            except Exception as exc:  # pragma: no cover - close is best effort
                log.warning("db_close_failed", engine=engine, error=str(exc))


@contextmanager
def authoritative(cursor):
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
    cursor = RoutingCursor()
    try:
        yield cursor
    finally:
        cursor.close()


hive_cursor = db_cursor


def get_cursor():
    cursor = RoutingCursor()
    try:
        yield cursor
    finally:
        cursor.close()


def execute(cursor, sql: str, params: tuple = ()):
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
