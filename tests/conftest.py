import itertools
import json
import re
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from app.crud import patients as patients_crud
from app.db import get_cursor
from app.main import app
from app.security import KNOWN_PERMISSIONS, MODEL_ACTIONS


ADMIN_ID = "user-admin"
VIEWER_ID = "user-viewer"
NOBODY_ID = "user-nobody"

ADMIN_USER = "admin"
VIEWER_USER = "viewer"
NOBODY_USER = "nobody"

ALL_PERMISSIONS = sorted(KNOWN_PERMISSIONS)

READONLY_PERMISSIONS = [
    f"{model}:{'read' if 'read' in actions else 'view'}"
    for model, actions in MODEL_ACTIONS.items()
]


def _seed():
    return {
        "roles": [
            {"id": "role-admin", "name": "admin", "permissions": ALL_PERMISSIONS},
            {"id": "role-viewer", "name": "viewer", "permissions": READONLY_PERMISSIONS},
            {"id": "role-none", "name": "none", "permissions": []},
        ],
        "users": [
            _user(ADMIN_ID, "admin", "role-admin"),
            _user(VIEWER_ID, "viewer", "role-viewer"),
            _user(NOBODY_ID, "nobody", "role-none"),
        ],
        "patient": [],
        "patient_applications": [],
        "patient_application_files": [],
        "file_metadata": [],
        "audit_logs": [],
        "access_logs": [],
        "intake_files": [],
        "intake_batches": [],
    }


def _user(user_id: str, username: str, role_id: str, is_active: bool = True):
    return {
        "id": user_id,
        "username": username,
        "email": f"{username}@example.com",
        "first_name": username.title(),
        "last_name": "Test",
        "status": "active",
        "is_active": is_active,
        "role_id": role_id,
        "created_at": datetime(2026, 7, 1, 12, 0, 0),
    }



_SELECT = re.compile(r"^SELECT (?P<cols>.+?) FROM `(?P<table>\w+)`(?P<rest>.*)$", re.S)
_INSERT = re.compile(
    r"^INSERT INTO `(?P<table>\w+)` \((?P<cols>.+?)\) VALUES \((?P<vals>.+)\)$", re.S
)
_INSERT_PARTITIONED = re.compile(
    r"^INSERT INTO TABLE `(?P<table>\w+)` "
    r"PARTITION \(`(?P<part>\w+)` = %s\) \((?P<cols>.+?)\) VALUES (?P<rows>.+)$",
    re.S,
)
_UPDATE = re.compile(r"^UPDATE `(?P<table>\w+)` SET (?P<sets>.+?) WHERE `(?P<key>\w+)` = %s$", re.S)
_UPDATE_IN = re.compile(
    r"^UPDATE `(?P<table>\w+)` SET (?P<sets>.+?) WHERE `(?P<key>\w+)` IN \((?P<slots>[%s, ]+)\)$", re.S
)
# A condition that consumes parameters, in the order it appears: `col` op %s,
# substr(`col`, 1, n) IN (...), or `col` IN (...).
_CONDITION = re.compile(
    r"substr\(`(?P<scol>\w+)`, 1, (?P<n>\d+)\) IN \((?P<sslots>[%s, ]+)\)"
    r"|`(?P<icol>\w+)` IN \((?P<islots>[%s, ]+)\)"
    r"|`(?P<col>\w+)` (?P<op>=|>=|<=|<|>) %s"
)
_CASE = re.compile(r"^CASE `(?P<col>\w+)` (?P<whens>(?:WHEN %s THEN %s ?)+)ELSE `(?P<else>\w+)` END$")
_DELETE = re.compile(r"^DELETE FROM `(?P<table>\w+)` WHERE `(?P<key>\w+)` = %s$", re.S)
_DELETE_IN = re.compile(r"^DELETE FROM `(?P<table>\w+)` WHERE `(?P<key>\w+)` IN \((?P<slots>[%s, ]+)\)$", re.S)
_WHERE = re.compile(r"`(?P<col>\w+)` (?P<op>=|>=|<=|<|>) %s")
_COL = re.compile(r"`(\w+)`")


class FakeHiveCursor:

    def __init__(self, store):
        self.store = store
        self.statements = []
        self._result = []


    def execute(self, sql, params=()):
        normalised = " ".join(sql.split())
        self.statements.append((normalised, params))
        params = list(params or ())

        if normalised.startswith("SELECT u.`id`"):
            self._result = self._select_users_with_role(normalised, params)
        elif normalised.startswith("SELECT"):
            self._result = self._select(normalised, params)
        elif normalised.startswith("INSERT"):
            self._result = self._insert(normalised, params)
        elif normalised.startswith("UPDATE"):
            self._result = self._update(normalised, params)
        elif normalised.startswith("DELETE"):
            self._result = self._delete(normalised, params)
        else:
            raise AssertionError(f"FakeHiveCursor cannot answer: {normalised}")

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return list(self._result)

    def close(self):
        pass


    def _rows(self, table):
        if table not in self.store:
            raise AssertionError(f"unknown table '{table}'")
        return self.store[table]

    def _select(self, sql, params):
        match = _SELECT.match(sql)
        assert match, f"unparsed SELECT: {sql}"
        table, rest = match.group("table"), match.group("rest")
        columns = _COL.findall(match.group("cols"))

        rows = _filter(list(self._rows(table)), rest.split(" GROUP BY ")[0], params)

        if " GROUP BY " in rest:
            keys = _COL.findall(rest.split(" GROUP BY ")[1])
            groups: dict = {}
            for row in rows:
                groups.setdefault(tuple(row.get(k) for k in keys), []).append(row)
            return [key + (len(members),) for key, members in groups.items()]

        if "ORDER BY `created_at` DESC" in rest:
            rows.sort(key=lambda r: str(r.get("created_at")), reverse=True)

        if "ORDER BY `found_at` DESC" in rest:
            rows.sort(key=lambda r: str(r.get("found_at")), reverse=True)

        limit = re.search(r"LIMIT (\d+)(?: OFFSET (\d+))?", rest)
        if limit:
            start = int(limit.group(2) or 0)
            rows = rows[start : start + int(limit.group(1))]

        return [tuple(_wire(r.get(c)) for c in columns) for r in rows]

    def _select_users_with_role(self, sql, params):
        rows = list(self._rows("users"))
        where = re.search(r"WHERE u\.`(\w+)` = %s", sql)
        if where:
            rows = [r for r in rows if r.get(where.group(1)) == params[0]]

        roles = {r["id"]: r for r in self._rows("roles")}
        out = []
        for row in rows:
            role = roles.get(row.get("role_id"))
            out.append(
                (
                    row["id"], row["username"], row["email"], row["first_name"],
                    row["last_name"], row["status"], row["is_active"],
                    row["role_id"], row["created_at"],
                    role["name"] if role else None,
                    _wire(role["permissions"]) if role else None,
                )
            )
        return out

    def _insert(self, sql, params):
        partitioned = _INSERT_PARTITIONED.match(sql)
        if partitioned:
            return self._insert_partitioned(partitioned, params)

        match = _INSERT.match(sql)
        assert match, f"unparsed INSERT: {sql}"
        columns = _COL.findall(match.group("cols"))

        tuples = _tuples(sql.split(" VALUES ", 1)[1])
        if len(tuples) > 1:
            for group in tuples:
                values = [_eval_value(e, params) for e in _split_values(group)]
                self._rows(match.group("table")).append(dict(zip(columns, values)))
            assert not params, f"INSERT binds {len(params)} params too many: {sql}"
            return []

        expressions = _split_values(match.group("vals"))
        assert len(columns) == len(expressions), (
            f"INSERT into `{match.group('table')}` supplies "
            f"{len(expressions)} values for {len(columns)} columns"
        )

        values = [_eval_value(e, params) for e in expressions]
        assert not params, f"INSERT binds {len(params)} params too many: {sql}"
        self._rows(match.group("table")).append(dict(zip(columns, values)))
        return []

    def _insert_partitioned(self, match, params):
        columns = _COL.findall(match.group("cols"))
        partition_value = params.pop(0)

        row_count = match.group("rows").count("(")
        assert len(params) == row_count * len(columns), (
            f"batched INSERT binds {len(params)} params for "
            f"{row_count} rows x {len(columns)} columns"
        )

        rows = self._rows(match.group("table"))
        for index in range(row_count):
            start = index * len(columns)
            values = params[start : start + len(columns)]
            row = dict(zip(columns, values))
            row[match.group("part")] = partition_value
            rows.append(row)

        return []

    def _update(self, sql, params):
        many = _UPDATE_IN.match(sql)
        match = many or _UPDATE.match(sql)
        assert match, f"unparsed UPDATE: {sql}"

        assignments = {}
        for part in _split_values(match.group("sets")):
            column, _, expression = part.partition(" = ")
            case = _CASE.match(expression.strip())
            if case:
                pairs = case.group("whens").count("WHEN")
                mapping = {}
                for _ in range(pairs):
                    when = params.pop(0)
                    mapping[when] = params.pop(0)
                assignments[_COL.findall(column)[0]] = ("case", case.group("col"), mapping)
            else:
                assignments[_COL.findall(column)[0]] = _eval_value(expression, params)

        keys = set(params) if many else {params.pop()}
        if not many:
            assert not params, f"UPDATE binds {len(params)} params too many: {sql}"

        for row in self._rows(match.group("table")):
            if row.get(match.group("key")) not in keys:
                continue
            for column, value in assignments.items():
                if isinstance(value, tuple) and value and value[0] == "case":
                    _, on, mapping = value
                    if row.get(on) in mapping:
                        row[column] = mapping[row.get(on)]
                else:
                    row[column] = value
        return []

    def _delete(self, sql, params):
        match = _DELETE.match(sql)
        if match:
            table, key = match.group("table"), match.group("key")
            self.store[table] = [
                r for r in self._rows(table) if r.get(key) != params[0]
            ]
            return []

        match = _DELETE_IN.match(sql)
        assert match, f"unparsed DELETE: {sql}"
        table, key = match.group("table"), match.group("key")
        wanted = set(params)
        self.store[table] = [r for r in self._rows(table) if r.get(key) not in wanted]
        return []


def _filter(rows, clause, params):
    """Apply every parameter-consuming condition, in the order written."""
    for cond in _CONDITION.finditer(clause):
        if cond.group("scol"):
            count = cond.group("sslots").count("%s")
            wanted = {params.pop(0) for _ in range(count)}
            n = int(cond.group("n"))
            rows = [r for r in rows if str(r.get(cond.group("scol")) or "")[:n] in wanted]
        elif cond.group("icol"):
            count = cond.group("islots").count("%s")
            wanted = {params.pop(0) for _ in range(count)}
            rows = [r for r in rows if r.get(cond.group("icol")) in wanted]
        else:
            rows = _compare(rows, cond.group("col"), cond.group("op"), params.pop(0))
    return rows


def _tuples(values_clause):
    """`(a, b), (c, d)` -> ["a, b", "c, d"], respecting nested parens."""
    groups, depth, start = [], 0, None
    for index, char in enumerate(values_clause):
        if char == "(":
            if depth == 0:
                start = index + 1
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                groups.append(values_clause[start:index])
    return groups


def _compare(rows, column, op, wanted):
    if op == "=":
        return [r for r in rows if r.get(column) == wanted]

    def key(row):
        value = row.get(column)
        return str(value) if value is not None else ""

    target = str(wanted)
    tests = {
        ">=": lambda r: key(r) >= target,
        ">": lambda r: key(r) > target,
        "<=": lambda r: key(r) <= target,
        "<": lambda r: key(r) < target,
    }
    return [r for r in rows if tests[op](r)]


def _split_values(clause):
    parts, depth, start = [], 0, 0
    for index, char in enumerate(clause):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(clause[start:index].strip())
            start = index + 1
    parts.append(clause[start:].strip())
    return parts


def _eval_value(expression, params):
    slots = expression.count("%s")
    if slots == 1:
        return params.pop(0)
    if slots > 1:
        return [params.pop(0) for _ in range(slots)]
    if expression.startswith("array("):
        return []
    if expression.startswith("current_timestamp()"):
        return datetime.now()
    if "NULL" in expression.upper():
        return None
    raise AssertionError(f"FakeHiveCursor cannot evaluate: {expression}")


def _wire(value):
    if isinstance(value, list):
        return json.dumps(value).encode("utf-8")
    if isinstance(value, (datetime, date)):
        return value
    return value




@pytest.fixture
def store():
    return _seed()


@pytest.fixture
def cursor(store):
    return FakeHiveCursor(store)


# Every module that opens its own connection instead of taking the
# request's cursor -- background work, mostly. A module missing from here
# does not fail loudly: it reaches the *real* database, and a test that
# quietly writes to production Hive is worse than one that errors.
_OPENS_ITS_OWN_CURSOR = (
    "app.audit",
    "app.deid",
    "app.deid_notices",
    "app.submission",
    "app.uploads",
    "app.access_log",
    "app.intake_worker",
    "app.intake_run",
)


@pytest.fixture
def patched_hive(cursor, monkeypatch):
    """Point every module that opens its own cursor at the fake store."""
    import contextlib

    @contextlib.contextmanager
    def fake_hive_cursor():
        yield cursor

    for module in _OPENS_ITS_OWN_CURSOR:
        monkeypatch.setattr(f"{module}.hive_cursor", fake_hive_cursor)

    return cursor


@pytest.fixture
def client(cursor, patched_hive):
    app.dependency_overrides[get_cursor] = lambda: cursor
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def as_admin(client):
    client.headers.update({"REMOTE-USER": ADMIN_USER})
    return client


@pytest.fixture(autouse=True)
def _no_real_database(monkeypatch):
    """Make reaching the real Hive from a test an error, not a quiet write.

    `_OPENS_ITS_OWN_CURSOR` redirects the modules it names. A module it
    misses -- a new one, or one importing hive_cursor inside a function --
    used to fall through to the live database and write there silently.
    This catches it at the one place every connection is made.
    """

    def refuse(engine, *args, **kwargs):
        raise AssertionError(
            f"a test tried to open a real {engine} connection -- add the "
            "module that did it to _OPENS_ITS_OWN_CURSOR in conftest.py"
        )

    monkeypatch.setattr("app.db._connect", refuse)


@pytest.fixture(autouse=True)
def _no_real_storage(tmp_path, monkeypatch):
    """Point every folder configured by environment at the test's tmp dir.

    Applies to every test, asked for or not. A test that forgets would
    otherwise write into the repo's own storage/ -- which is exactly what
    happened when submission started filing under SUBMITTED_DIR.
    """
    monkeypatch.setenv("INTAKE_DIR", str(tmp_path / "incoming_data"))
    monkeypatch.setenv("SUBMITTED_DIR", str(tmp_path / "submitted"))


@pytest.fixture
def storage_root(tmp_path, monkeypatch):
    root = tmp_path / "patient_files"
    monkeypatch.setattr("app.storage.STORAGE_ROOT", root)
    return root


@pytest.fixture
def access_events(cursor, monkeypatch):
    from app import access_log

    monkeypatch.setattr(access_log, "_ensure_writer", lambda: None)

    class Events:
        def flush(self):
            access_log.flush_once()
            return self.rows

        @property
        def rows(self):
            return cursor.store["access_logs"]

        def of(self, action):
            return [row for row in self.rows if row["action"] == action]

    while True:
        try:
            access_log._queue.get_nowait()
        except Exception:
            break

    return Events()


@pytest.fixture
def sent_emails(monkeypatch):
    outbox = []

    def fake_send(to, subject, body, html=None):
        recipients = [address for address in to if address]
        if not recipients:
            return False
        outbox.append({"to": recipients, "subject": subject, "body": body})
        return True

    monkeypatch.setattr("app.notifications.send_email", fake_send)
    return outbox


_code_counter = itertools.count(1)


def next_patient_code() -> str:
    """A fresh, valid code per call -- codes are supplied now, not generated."""
    return f"AA{next(_code_counter):04d}"


def minimal_patient(**overrides):
    return {
        "id": next_patient_code(),
        "fstname": "Jane",
        "original_file_path": "/data/jane.pdf",
        **overrides,
    }


def patient_columns():
    return list(patients_crud.COLUMNS)
