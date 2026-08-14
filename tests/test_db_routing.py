"""Which engine runs which statement.

Queries go to Impala; everything that writes goes to Hive, because these
tables are full-ACID ORC and Impala will not write to those. Getting it
wrong is quiet in one direction and loud in the other -- a query sent to
Hive merely runs slower, while a write sent to Impala is refused -- so
the mapping is pinned rather than left to be discovered in production.
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
        # Not Impala: these tables are full-ACID ORC, and it will not
        # write to those. Everything that writes belongs to Hive.
        ("INSERT INTO TABLE patient (id) VALUES (%s)", db.HIVE),
        ("insert into patient (id) values (%s)", db.HIVE),
        ("UPDATE patient SET fstname = %s WHERE id = %s", db.HIVE),
        ("update patient set fstname = %s", db.HIVE),
        ("DELETE FROM patient WHERE id = %s", db.HIVE),
        ("MERGE INTO patient USING x ON y", db.HIVE),
        ("CREATE TABLE t (a INT)", db.HIVE),
        ("ALTER TABLE t ADD COLUMNS (b INT)", db.HIVE),
        ("TRUNCATE TABLE t", db.HIVE),
        ("SHOW TABLES", db.HIVE),
        ("DESCRIBE patient", db.HIVE),
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
    # No database by default, so the routing tests below assert on the
    # statements they ran and nothing else. The tests that care about it
    # set it themselves.
    monkeypatch.setattr(db, "IMPALA_DB", "")
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
    """The ordinary shape: read the row, write it, record what happened."""
    cursor = db.RoutingCursor()

    cursor.execute("SELECT * FROM patient WHERE id = %s", ("P1",))
    cursor.execute("UPDATE patient SET fstname = %s WHERE id = %s", ("A", "P1"))
    cursor.execute("INSERT INTO TABLE audit_logs (id) VALUES (%s)", ("a1",))

    assert engines[db.IMPALA].cursors[0].statements == [
        "SELECT * FROM patient WHERE id = %s",
    ]
    assert engines[db.HIVE].cursors[0].statements == [
        "UPDATE patient SET fstname = %s WHERE id = %s",
        "INSERT INTO TABLE audit_logs (id) VALUES (%s)",
    ]


def test_each_engine_gets_one_cursor_not_one_per_statement(engines):
    cursor = db.RoutingCursor()

    for _ in range(3):
        cursor.execute("SELECT 1")

    assert len(engines[db.IMPALA].cursors) == 1


def test_results_come_from_the_engine_that_ran_the_statement(engines):
    """A fetch must read from the cursor that ran the statement, not from
    whichever connection happened to be opened first."""
    cursor = db.RoutingCursor()

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


# ------------------------------------------------- pointing at a database


def test_an_impala_session_is_pointed_at_the_database(engines, monkeypatch):
    """The data connection carries no database, so an unqualified `users`
    lands in `default` -- and Impala calls that a privilege error rather
    than a missing table."""
    monkeypatch.setattr(db, "IMPALA_DB", "hive_app")

    cursor = db.RoutingCursor()
    cursor.execute("SELECT * FROM users")

    assert engines[db.IMPALA].cursors[0].statements == [
        "USE `hive_app`",
        "SELECT * FROM users",
    ]


def test_the_database_is_set_once_per_session_not_per_statement(engines, monkeypatch):
    monkeypatch.setattr(db, "IMPALA_DB", "hive_app")

    cursor = db.RoutingCursor()
    cursor.execute("SELECT 1")
    cursor.execute("SELECT 2")

    uses = [s for s in engines[db.IMPALA].cursors[0].statements if s.startswith("USE")]
    assert len(uses) == 1


def test_hive_is_left_alone(engines, monkeypatch):
    """It takes the database as a connection parameter already."""
    monkeypatch.setattr(db, "IMPALA_DB", "hive_app")

    cursor = db.RoutingCursor()
    cursor.execute("DELETE FROM users WHERE id = %s", ("u1",))

    assert engines[db.HIVE].cursors[0].statements == [
        "DELETE FROM users WHERE id = %s"
    ]


def test_no_database_configured_changes_nothing(engines, monkeypatch):
    monkeypatch.setattr(db, "IMPALA_DB", "")

    cursor = db.RoutingCursor()
    cursor.execute("SELECT 1")

    assert engines[db.IMPALA].cursors[0].statements == ["SELECT 1"]


@pytest.mark.parametrize(
    "name", ["a; DROP TABLE users", "has space", "1leading", "back`tick", "-"]
)
def test_a_database_name_that_is_not_an_identifier_is_refused(name):
    """It goes into the statement as an identifier, which cannot be bound
    as a parameter -- so it is checked instead of trusted."""
    with pytest.raises(DatabaseError):
        db.use_database(FakeCursor("impala"), name)


# ------------------------------------------- seeing what you just wrote


@pytest.mark.parametrize(
    "sql,table",
    [
        ("INSERT INTO `patient` (id) VALUES (%s)", "patient"),
        ("insert into patient (id) values (%s)", "patient"),
        ("INSERT INTO TABLE `access_logs` PARTITION (d = %s) (id) VALUES (%s)",
         "access_logs"),
        ("INSERT OVERWRITE TABLE t SELECT 1", "t"),
        ("UPDATE `patient` SET fstname = %s", "patient"),
        ("DELETE FROM `patient` WHERE id = %s", "patient"),
        ("MERGE INTO patient USING x ON y", "patient"),
        ("SELECT * FROM patient", ""),
        ("", ""),
    ],
)
def test_the_table_a_write_lands_on(sql, table):
    assert db.written_table(sql) == table


def test_a_row_can_be_read_back_in_the_call_that_wrote_it(engines):
    """Creating a patient inserts, then reads the row back to return it.
    Impala knows nothing of a Hive write until it is refreshed, so that
    read came back empty and the API answered 404 for a patient it had
    just created."""
    cursor = db.RoutingCursor()

    cursor.execute("INSERT INTO `patient` (id) VALUES (%s)", ("P1",))
    cursor.execute("SELECT * FROM `patient` WHERE id = %s", ("P1",))

    assert cursor.fetchone() == (db.HIVE,), "read back from the engine that wrote it"
    assert db.IMPALA not in engines, "and without troubling Impala at all"


def test_reads_before_any_write_still_go_to_impala(engines):
    """The rule is read-your-own-write, not give-up-on-Impala."""
    cursor = db.RoutingCursor()

    cursor.execute("SELECT * FROM patient")
    assert cursor.fetchone() == (db.IMPALA,)

    cursor.execute("UPDATE patient SET fstname = %s", ("A",))
    cursor.execute("SELECT * FROM patient")
    assert cursor.fetchone() == (db.HIVE,)


def test_impala_is_told_about_the_tables_that_were_written(engines, monkeypatch):
    """Otherwise the next request -- the list the page reloads -- is
    answered from what the table looked like before the write."""
    monkeypatch.setattr(db, "REFRESH_AFTER_WRITE", True)
    cursor = db.RoutingCursor()

    cursor.execute("INSERT INTO `patient` (id) VALUES (%s)", ("P1",))
    cursor.execute("INSERT INTO `audit_logs` (id) VALUES (%s)", ("a1",))
    cursor.close()

    assert engines[db.IMPALA].cursors[0].statements == [
        "REFRESH audit_logs",
        "REFRESH patient",
    ]


def test_a_table_written_repeatedly_is_refreshed_once(engines, monkeypatch):
    monkeypatch.setattr(db, "REFRESH_AFTER_WRITE", True)
    cursor = db.RoutingCursor()

    for n in range(3):
        cursor.execute("INSERT INTO `patient` (id) VALUES (%s)", (n,))
    cursor.close()

    assert engines[db.IMPALA].cursors[0].statements == ["REFRESH patient"]


def test_a_read_only_request_refreshes_nothing(engines, monkeypatch):
    monkeypatch.setattr(db, "REFRESH_AFTER_WRITE", True)
    cursor = db.RoutingCursor()

    cursor.execute("SELECT 1")
    cursor.close()

    assert engines[db.IMPALA].cursors[0].statements == ["SELECT 1"]


def test_a_refresh_that_fails_does_not_fail_the_request(monkeypatch):
    """The write already succeeded. A missed refresh costs a stale read,
    not a lost row, so it must not turn a saved patient into an error."""

    class ExplodingCursor(FakeCursor):
        def execute(self, sql, params=()):
            raise RuntimeError("catalog is unhappy")

    class ExplodingConnection(FakeConnection):
        def cursor(self):
            return ExplodingCursor(self.engine)

    monkeypatch.setattr(
        db,
        "_connect",
        lambda engine: (
            ExplodingConnection(engine)
            if engine == db.IMPALA
            else FakeConnection(engine)
        ),
    )
    monkeypatch.setattr(db, "impala_available", lambda: True)
    monkeypatch.setattr(db, "IMPALA_DB", "")
    monkeypatch.setattr(db, "REFRESH_AFTER_WRITE", True)

    cursor = db.RoutingCursor()
    cursor.execute("INSERT INTO `patient` (id) VALUES (%s)", ("P1",))

    cursor.close()  # must not raise


def test_refresh_can_be_switched_off(engines, monkeypatch):
    monkeypatch.setattr(db, "REFRESH_AFTER_WRITE", False)
    cursor = db.RoutingCursor()

    cursor.execute("DELETE FROM `patient` WHERE id = %s", ("P1",))
    cursor.close()

    assert db.IMPALA not in engines
