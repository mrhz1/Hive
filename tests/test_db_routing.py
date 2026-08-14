"""Which engine runs which statement.

Reads and inserts go to Impala, updates and deletes to Hive. Getting
this wrong is quiet -- the statement still runs, just on the engine that
was not meant to have it -- so the mapping is pinned rather than left to
be noticed in a query log.
"""
import pytest

from app import db
from app.errors import DatabaseError


@pytest.mark.parametrize(
    "sql,engine",
    [
        ("SELECT * FROM patient", db.IMPALA),
        ("select 1", db.IMPALA),
        ("  \n SELECT 1", db.IMPALA),
        ("WITH recent AS (SELECT 1) SELECT * FROM recent", db.IMPALA),
        ("(SELECT 1) UNION ALL (SELECT 2)", db.IMPALA),
        ("INSERT INTO TABLE patient (id) VALUES (%s)", db.IMPALA),
        ("SHOW TABLES", db.IMPALA),
        ("DESCRIBE patient", db.IMPALA),
        ("REFRESH patient", db.IMPALA),
        ("INVALIDATE METADATA patient", db.IMPALA),
        ("UPDATE patient SET fstname = %s WHERE id = %s", db.HIVE),
        ("update patient set fstname = %s", db.HIVE),
        ("DELETE FROM patient WHERE id = %s", db.HIVE),
        ("MERGE INTO patient USING x ON y", db.HIVE),
        ("CREATE TABLE t (a INT)", db.HIVE),
        ("ALTER TABLE t ADD COLUMNS (b INT)", db.HIVE),
        ("TRUNCATE TABLE t", db.HIVE),
        # Nothing recognisable goes to the engine that can run everything.
        ("", db.HIVE),
        ("   ", db.HIVE),
        ("GRANT SELECT ON t TO ROLE r", db.HIVE),
    ],
)
def test_the_engine_a_statement_goes_to(sql, engine):
    assert db.engine_for(sql) == engine


# ------------------------------------------------------ the routing cursor


class FakeCursor:
    def __init__(self, engine):
        self.engine = engine
        self.statements = []

    def execute(self, sql, params=()):
        self.statements.append(sql)

    def fetchall(self):
        return [(self.engine,)]

    def fetchone(self):
        return (self.engine,)


class FakeConnection:
    def __init__(self, engine):
        self.engine = engine
        self.closed = False
        self.cursors = []

    def cursor(self):
        cursor = FakeCursor(self.engine)
        self.cursors.append(cursor)
        return cursor

    def close(self):
        self.closed = True


@pytest.fixture
def engines(monkeypatch):
    """Both engines, recording which one was asked for."""
    opened = {}

    def fake_connect(engine):
        opened[engine] = opened.get(engine) or FakeConnection(engine)
        return opened[engine]

    monkeypatch.setattr(db, "_connect", fake_connect)
    monkeypatch.setattr(db, "impala_available", lambda: True)
    return opened


def test_a_read_only_request_never_opens_hive(engines):
    cursor = db.RoutingCursor()

    cursor.execute("SELECT 1")
    cursor.execute("SELECT 2")

    assert set(engines) == {db.IMPALA}


def test_a_delete_only_request_never_opens_impala(engines):
    cursor = db.RoutingCursor()

    cursor.execute("DELETE FROM patient WHERE id = %s", ("P1",))

    assert set(engines) == {db.HIVE}


def test_one_request_can_use_both(engines):
    """The ordinary shape: read the row, then write it."""
    cursor = db.RoutingCursor()

    cursor.execute("SELECT * FROM patient WHERE id = %s", ("P1",))
    cursor.execute("UPDATE patient SET fstname = %s WHERE id = %s", ("A", "P1"))
    cursor.execute("INSERT INTO TABLE audit_logs (id) VALUES (%s)", ("a1",))

    assert engines[db.IMPALA].cursors[0].statements == [
        "SELECT * FROM patient WHERE id = %s",
        "INSERT INTO TABLE audit_logs (id) VALUES (%s)",
    ]
    assert engines[db.HIVE].cursors[0].statements == [
        "UPDATE patient SET fstname = %s WHERE id = %s"
    ]


def test_each_engine_gets_one_cursor_not_one_per_statement(engines):
    cursor = db.RoutingCursor()

    for _ in range(3):
        cursor.execute("SELECT 1")

    assert len(engines[db.IMPALA].cursors) == 1


def test_results_come_from_the_engine_that_ran_the_statement(engines):
    """A fetchall() after a SELECT must not read from the Hive cursor
    just because a write happened to open one first."""
    cursor = db.RoutingCursor()

    cursor.execute("DELETE FROM patient WHERE id = %s", ("P1",))
    cursor.execute("SELECT * FROM patient")

    assert cursor.fetchall() == [(db.IMPALA,)]

    cursor.execute("UPDATE patient SET fstname = %s", ("A",))
    assert cursor.fetchone() == (db.HIVE,)


def test_reading_before_running_anything_says_so(engines):
    cursor = db.RoutingCursor()

    with pytest.raises(DatabaseError):
        cursor.fetchall()


def test_closing_closes_every_connection_opened(engines):
    cursor = db.RoutingCursor()
    cursor.execute("SELECT 1")
    cursor.execute("DELETE FROM patient")

    cursor.close()

    assert all(connection.closed for connection in engines.values())


def test_without_impala_everything_goes_to_hive(monkeypatch):
    """A laptop has no cml.data_v1 and no connection name. The split is a
    deployment concern; local development must not need an Impala."""
    opened = {}

    def fake_connect(engine):
        opened[engine] = opened.get(engine) or FakeConnection(engine)
        return opened[engine]

    monkeypatch.setattr(db, "_connect", fake_connect)
    monkeypatch.setattr(db, "impala_available", lambda: False)

    cursor = db.RoutingCursor()
    cursor.execute("SELECT 1")
    cursor.execute("INSERT INTO TABLE t (a) VALUES (1)")

    assert set(opened) == {db.HIVE}


def test_impala_is_unavailable_without_a_connection_name(monkeypatch):
    monkeypatch.setattr(db, "IMPALA_CONNECTION", "")

    assert db.impala_available() is False
