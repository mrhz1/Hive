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
        ("", db.HIVE),
        ("   ", db.HIVE),
        ("GRANT SELECT ON t TO ROLE r", db.HIVE),
    ],
)
def test_the_engine_a_statement_goes_to(sql, engine):
    assert db.engine_for(sql) == engine




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
    opened = {}

    def fake_connect(engine):
        opened[engine] = opened.get(engine) or FakeConnection(engine)
        return opened[engine]

    monkeypatch.setattr(db, "_connect", fake_connect)
    monkeypatch.setattr(db, "impala_available", lambda: True)
    monkeypatch.setattr(db, "IMPALA_DB", "")
    monkeypatch.setattr(db, "IMPALA_POOL", False)
    monkeypatch.setattr(db, "HIVE_POOL", False)
    db.discard_sessions()
    yield opened
    db.discard_sessions()


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




def test_an_impala_session_is_pointed_at_the_database(engines, monkeypatch):
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
    with pytest.raises(DatabaseError):
        db.use_database(FakeCursor("impala"), name)




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
    cursor = db.RoutingCursor()

    cursor.execute("INSERT INTO `patient` (id) VALUES (%s)", ("P1",))
    cursor.execute("SELECT * FROM `patient` WHERE id = %s", ("P1",))

    assert cursor.fetchone() == (db.HIVE,), "read back from the engine that wrote it"
    assert db.IMPALA not in engines, "and without troubling Impala at all"


def test_reads_before_any_write_still_go_to_impala(engines):
    cursor = db.RoutingCursor()

    cursor.execute("SELECT * FROM patient")
    assert cursor.fetchone() == (db.IMPALA,)

    cursor.execute("UPDATE patient SET fstname = %s", ("A",))
    cursor.execute("SELECT * FROM patient")
    assert cursor.fetchone() == (db.HIVE,)


def test_impala_is_told_about_the_tables_that_were_written(engines, monkeypatch):
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

    cursor.close()


def test_refresh_can_be_switched_off(engines, monkeypatch):
    monkeypatch.setattr(db, "REFRESH_AFTER_WRITE", False)
    cursor = db.RoutingCursor()

    cursor.execute("DELETE FROM `patient` WHERE id = %s", ("P1",))
    cursor.close()

    assert db.IMPALA not in engines




@pytest.fixture
def pooled(engines, monkeypatch):
    monkeypatch.setattr(db, "IMPALA_POOL", True)
    monkeypatch.setattr(db, "HIVE_POOL", True)
    db.discard_sessions()
    yield engines
    db.discard_sessions()


def test_a_second_request_does_not_authenticate_again(pooled):
    for _ in range(4):
        cursor = db.RoutingCursor()
        cursor.execute("SELECT * FROM patient")
        cursor.close()

    assert len(pooled[db.IMPALA].cursors) == 1, "reopened the connection"
    assert pooled[db.IMPALA].closed is False, "closing a request closed the session"


def test_the_database_is_set_once_for_the_whole_session(pooled, monkeypatch):
    monkeypatch.setattr(db, "IMPALA_DB", "hive_app")
    db.discard_sessions()

    for _ in range(3):
        cursor = db.RoutingCursor()
        cursor.execute("SELECT 1")
        cursor.close()

    statements = pooled[db.IMPALA].cursors[0].statements
    assert statements.count("USE `hive_app`") == 1


def test_hive_is_pooled_too(pooled):
    for _ in range(3):
        cursor = db.RoutingCursor()
        cursor.execute("DELETE FROM patient WHERE id = %s", ("P1",))
        cursor.close()

    assert len(pooled[db.HIVE].cursors) == 1, "reopened the connection"
    assert pooled[db.HIVE].closed is False


def test_a_session_that_died_while_parked_is_reopened(monkeypatch):
    attempts = {"n": 0}

    class SometimesDead(FakeCursor):
        def execute(self, sql, params=()):
            attempts["n"] += 1
            if attempts["n"] == 2:
                raise RuntimeError("session expired")
            return super().execute(sql, params)

    class Connection(FakeConnection):
        def cursor(self):
            cursor = SometimesDead(self.engine)
            self.cursors.append(cursor)
            return cursor

    opened = []

    def fake_connect(engine):
        connection = Connection(engine)
        opened.append(connection)
        return connection

    monkeypatch.setattr(db, "_connect", fake_connect)
    monkeypatch.setattr(db, "impala_available", lambda: True)
    monkeypatch.setattr(db, "IMPALA_DB", "")
    monkeypatch.setattr(db, "IMPALA_POOL", True)
    monkeypatch.setattr(db, "HIVE_POOL", False)
    db.discard_sessions()

    try:
        first = db.RoutingCursor()
        first.execute("SELECT 1")
        first.close()

        second = db.RoutingCursor()
        second.execute("SELECT 2")
        second.close()

        assert len(opened) == 2, "did not reopen after the session died"
        assert second.fetchall() == [(db.IMPALA,)]
    finally:
        db.discard_sessions()


def test_a_freshly_opened_session_is_not_retried(monkeypatch):
    attempts = {"n": 0}

    class AlwaysDead(FakeCursor):
        def execute(self, sql, params=()):
            attempts["n"] += 1
            raise RuntimeError("syntax error")

    class Connection(FakeConnection):
        def cursor(self):
            return AlwaysDead(self.engine)

    monkeypatch.setattr(db, "_connect", lambda engine: Connection(engine))
    monkeypatch.setattr(db, "impala_available", lambda: True)
    monkeypatch.setattr(db, "IMPALA_DB", "")
    monkeypatch.setattr(db, "IMPALA_POOL", True)
    monkeypatch.setattr(db, "HIVE_POOL", False)
    db.discard_sessions()

    try:
        cursor = db.RoutingCursor()
        with pytest.raises(RuntimeError):
            cursor.execute("SELECT nonsense")
        assert attempts["n"] == 1
    finally:
        db.discard_sessions()




class MissingFromImpala(FakeCursor):

    def fetchone(self):
        return None if self.engine == db.IMPALA else (self.engine,)

    def fetchall(self):
        return [] if self.engine == db.IMPALA else [(self.engine,)]


def test_a_read_can_be_forced_onto_the_engine_that_owns_the_row(engines):
    cursor = db.RoutingCursor()

    cursor.execute("SELECT * FROM patient WHERE id = %s", ("P1",))
    assert set(engines) == {db.IMPALA}

    with db.authoritative(cursor):
        cursor.execute("SELECT * FROM patient WHERE id = %s", ("P1",))

    assert cursor.fetchone() == (db.HIVE,)


def test_the_forcing_stops_at_the_end_of_the_block(engines):
    cursor = db.RoutingCursor()

    with db.authoritative(cursor):
        cursor.execute("SELECT 1")
    cursor.execute("SELECT 2")

    assert cursor.fetchone() == (db.IMPALA,)


def test_it_is_restored_even_if_the_read_raises(engines):
    cursor = db.RoutingCursor()

    with pytest.raises(RuntimeError):
        with db.authoritative(cursor):
            raise RuntimeError("query blew up")

    assert cursor.force_hive is False


def test_a_row_impala_cannot_see_yet_is_still_found(monkeypatch):
    from app.crud import patients as patients_crud

    class Connection(FakeConnection):
        def cursor(self):
            cursor = MissingFromImpala(self.engine)
            self.cursors.append(cursor)
            return cursor

    monkeypatch.setattr(db, "_connect", lambda engine: Connection(engine))
    monkeypatch.setattr(db, "impala_available", lambda: True)
    monkeypatch.setattr(db, "IMPALA_DB", "")
    monkeypatch.setattr(db, "IMPALA_POOL", False)
    monkeypatch.setattr(
        patients_crud, "_row_to_patient", lambda row: f"patient from {row[0]}"
    )

    cursor = db.RoutingCursor()

    assert patients_crud.get_patient_or_404(cursor, "P1") == "patient from hive"


def test_a_hive_write_is_not_retried_on_a_dropped_session(monkeypatch):
    attempts = {"n": 0}

    class DeadOnReuse(FakeCursor):
        def execute(self, sql, params=()):
            attempts["n"] += 1
            if attempts["n"] == 2:
                raise RuntimeError("session expired")
            return super().execute(sql, params)

    class Connection(FakeConnection):
        def cursor(self):
            cursor = DeadOnReuse(self.engine)
            self.cursors.append(cursor)
            return cursor

    monkeypatch.setattr(db, "_connect", lambda engine: Connection(engine))
    monkeypatch.setattr(db, "impala_available", lambda: True)
    monkeypatch.setattr(db, "IMPALA_DB", "")
    monkeypatch.setattr(db, "HIVE_POOL", True)
    monkeypatch.setattr(db, "IMPALA_POOL", False)
    monkeypatch.setattr(db, "REFRESH_AFTER_WRITE", False)
    db.discard_sessions()

    try:
        first = db.RoutingCursor()
        first.execute("DELETE FROM patient WHERE id = %s", ("P1",))
        first.close()

        second = db.RoutingCursor()
        with pytest.raises(RuntimeError):
            second.execute("DELETE FROM patient WHERE id = %s", ("P2",))

        assert attempts["n"] == 2, "the write was run a second time"

        third = db.RoutingCursor()
        third.execute("DELETE FROM patient WHERE id = %s", ("P3",))
    finally:
        db.discard_sessions()


def test_a_session_left_parked_too_long_is_replaced(monkeypatch):
    opened = []

    def fake_connect(engine):
        connection = FakeConnection(engine)
        opened.append(connection)
        return connection

    monkeypatch.setattr(db, "_connect", fake_connect)
    monkeypatch.setattr(db, "impala_available", lambda: True)
    monkeypatch.setattr(db, "IMPALA_DB", "")
    monkeypatch.setattr(db, "IMPALA_POOL", True)
    monkeypatch.setattr(db, "POOL_MAX_IDLE_SECONDS", 0)
    db.discard_sessions()

    try:
        for _ in range(2):
            cursor = db.RoutingCursor()
            cursor.execute("SELECT 1")
            cursor.close()

        assert len(opened) == 2, "an expired session was handed out again"
    finally:
        db.discard_sessions()




@pytest.mark.parametrize(
    "configured,expected",
    [
        (None, db.IMPALA),
        ("impala", db.IMPALA),
        ("IMPALA", db.IMPALA),
        (" impala ", db.IMPALA),
        ("hive", db.HIVE),
        ("Hive", db.HIVE),
        ("impla", db.HIVE),
        ("", db.IMPALA),
    ],
)
def test_the_read_engine_setting(configured, expected, monkeypatch):
    if configured is None:
        monkeypatch.delenv("READ_ENGINE", raising=False)
    else:
        monkeypatch.setenv("READ_ENGINE", configured)

    assert db._read_engine() == expected


def test_choosing_hive_sends_queries_there_too(monkeypatch):
    opened = {}

    def fake_connect(engine):
        opened[engine] = opened.get(engine) or FakeConnection(engine)
        return opened[engine]

    monkeypatch.setattr(db, "_connect", fake_connect)
    monkeypatch.setattr(db, "READ_ENGINE", db.HIVE)
    monkeypatch.setattr(db, "IMPALA_CONNECTION", "some-connection")
    monkeypatch.setattr(db, "IMPALA_POOL", False)
    monkeypatch.setattr(db, "HIVE_POOL", False)
    db.discard_sessions()

    assert db.impala_available() is False

    cursor = db.RoutingCursor()
    cursor.execute("SELECT * FROM patient")
    cursor.execute("DELETE FROM patient WHERE id = %s", ("P1",))

    assert set(opened) == {db.HIVE}, "Impala was used despite READ_ENGINE=hive"


def test_choosing_hive_also_stops_the_refresh(monkeypatch):
    opened = {}

    monkeypatch.setattr(
        db, "_connect", lambda engine: opened.setdefault(engine, FakeConnection(engine))
    )
    monkeypatch.setattr(db, "READ_ENGINE", db.HIVE)
    monkeypatch.setattr(db, "IMPALA_CONNECTION", "some-connection")
    monkeypatch.setattr(db, "REFRESH_AFTER_WRITE", True)
    monkeypatch.setattr(db, "HIVE_POOL", False)
    db.discard_sessions()

    cursor = db.RoutingCursor()
    cursor.execute("INSERT INTO `patient` (id) VALUES (%s)", ("P1",))
    cursor.close()

    assert db.IMPALA not in opened
