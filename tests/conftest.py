"""Test harness: an in-memory stand-in for HiveServer2.

The CRUD layer speaks raw HiveQL, so the only way to test it end to end
without a live metastore is to answer that SQL. FakeHiveCursor implements
exactly the statement shapes app/crud/* emits -- no more -- and returns
rows as positional tuples in the order the SELECT asked for.

KNOWN LIMIT: rows are stored by column *name*, taken from the INSERT's own
column list. Real Hive is positional against a fixed table schema, so it
would reject a mismatch between the INSERT list and the table -- this fake
cannot. A self-consistent reordering of crud.patients.COLUMNS therefore
passes here (verified by mutation) even though it is wrong against Hive.
sql/schema.sql is the guard for that: keep its column order identical to
COLUMNS. What these tests do cover is that every field survives the
round trip through the real router, schema and CRUD code.
"""
import json
import re
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from app.crud import patients as patients_crud
from app.db import get_cursor
from app.main import app
from app.security import PERMISSION_ACTIONS, PERMISSION_MODELS

# --------------------------------------------------------------- fixtures

ADMIN_ID = "user-admin"
VIEWER_ID = "user-viewer"
NOBODY_ID = "user-nobody"

# Requests authenticate as a *username* -- REMOTE-USER carries the name
# the platform authenticated, and the API resolves it to the row. The ids
# above are what the rows hold, and what the actor columns get stamped
# with, so tests need both.
ADMIN_USER = "admin"
VIEWER_USER = "viewer"
NOBODY_USER = "nobody"

# Derived from the app rather than restated, so adding a model or an
# action cannot leave the fixtures granting a set the API does not know.
ALL_PERMISSIONS = [
    f"{model}:{action}"
    for model in PERMISSION_MODELS
    for action in PERMISSION_ACTIONS
]
READONLY_PERMISSIONS = [f"{m}:view" for m in PERMISSION_MODELS]


def _seed():
    """A fresh store: two roles, three users, no patients."""
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


# ------------------------------------------------------------- the cursor

_SELECT = re.compile(r"^SELECT (?P<cols>.+?) FROM `(?P<table>\w+)`(?P<rest>.*)$", re.S)
_INSERT = re.compile(
    r"^INSERT INTO `(?P<table>\w+)` \((?P<cols>.+?)\) VALUES \((?P<vals>.+)\)$", re.S
)
_UPDATE = re.compile(r"^UPDATE `(?P<table>\w+)` SET (?P<sets>.+?) WHERE `(?P<key>\w+)` = %s$", re.S)
_DELETE = re.compile(r"^DELETE FROM `(?P<table>\w+)` WHERE `(?P<key>\w+)` = %s$", re.S)
_DELETE_IN = re.compile(r"^DELETE FROM `(?P<table>\w+)` WHERE `(?P<key>\w+)` IN \((?P<slots>[%s, ]+)\)$", re.S)
_WHERE = re.compile(r"WHERE `(?P<col>\w+)` = %s")
_COL = re.compile(r"`(\w+)`")


class FakeHiveCursor:
    """Answers the subset of HiveQL app/crud/* emits, against dict rows."""

    def __init__(self, store):
        self.store = store
        self.statements = []
        self._result = []

    # -- DBAPI surface ----------------------------------------------------

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

    # -- statement handlers -----------------------------------------------

    def _rows(self, table):
        if table not in self.store:
            raise AssertionError(f"unknown table '{table}'")
        return self.store[table]

    def _select(self, sql, params):
        match = _SELECT.match(sql)
        assert match, f"unparsed SELECT: {sql}"
        table, rest = match.group("table"), match.group("rest")
        columns = _COL.findall(match.group("cols"))

        rows = list(self._rows(table))
        for where in _WHERE.finditer(rest):
            wanted = params.pop(0)
            rows = [r for r in rows if r.get(where.group("col")) == wanted]

        if "ORDER BY `created_at` DESC" in rest:
            rows.sort(key=lambda r: str(r.get("created_at")), reverse=True)

        limit = re.search(r"LIMIT (\d+)", rest)
        if limit:
            rows = rows[: int(limit.group(1))]

        # Positional tuples, in the order the SELECT listed them.
        return [tuple(_wire(r.get(c)) for c in columns) for r in rows]

    def _select_users_with_role(self, sql, params):
        """The one JOIN in the codebase: users LEFT JOIN roles."""
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
        match = _INSERT.match(sql)
        assert match, f"unparsed INSERT: {sql}"
        columns = _COL.findall(match.group("cols"))
        expressions = _split_values(match.group("vals"))
        assert len(columns) == len(expressions), (
            f"INSERT into `{match.group('table')}` supplies "
            f"{len(expressions)} values for {len(columns)} columns"
        )

        values = [_eval_value(e, params) for e in expressions]
        assert not params, f"INSERT binds {len(params)} params too many: {sql}"
        self._rows(match.group("table")).append(dict(zip(columns, values)))
        return []

    def _update(self, sql, params):
        match = _UPDATE.match(sql)
        assert match, f"unparsed UPDATE: {sql}"
        key = params.pop()

        assignments = {}
        for part in _split_values(match.group("sets")):
            column, _, expression = part.partition(" = ")
            assignments[_COL.findall(column)[0]] = _eval_value(expression, params)
        assert not params, f"UPDATE binds {len(params)} params too many: {sql}"

        for row in self._rows(match.group("table")):
            if row.get(match.group("key")) == key:
                row.update(assignments)
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


def _split_values(clause):
    """Split a VALUES list or SET clause on its top-level commas.

    Not every value is a bare placeholder -- current_timestamp() and
    CAST(NULL AS TIMESTAMP) carry their own parens -- so a plain
    clause.split(",") would cut array(%s, %s) in half.
    """
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
    """One value expression, resolved to what Hive would store.

    Timestamps are written as SQL text rather than bound (see
    app/db.py::NOW_SQL), so they consume no parameter: this is where the
    fake plays the part of the server clock.
    """
    slots = expression.count("%s")
    if slots == 1:
        return params.pop(0)
    if slots > 1:
        # array(%s, %s, ...) -- the one multi-slot expression in the codebase.
        return [params.pop(0) for _ in range(slots)]
    if expression.startswith("array("):
        return []
    if expression.startswith("current_timestamp()"):
        return datetime.now()
    if "NULL" in expression.upper():
        return None
    raise AssertionError(f"FakeHiveCursor cannot evaluate: {expression}")


def _wire(value):
    """Values as the driver would hand them back.

    ARRAY<STRING> arrives as bytes holding a JSON array, not a list --
    app/crud/roles.py::_parse_permissions exists because of this, so the
    fake has to reproduce it or that code path is never exercised.
    """
    if isinstance(value, list):
        return json.dumps(value).encode("utf-8")
    if isinstance(value, (datetime, date)):
        return value
    return value


# --------------------------------------------------------------- fixtures


@pytest.fixture
def store():
    return _seed()


@pytest.fixture
def cursor(store):
    return FakeHiveCursor(store)


@pytest.fixture
def client(cursor, monkeypatch):
    """TestClient with Hive replaced by the fake, for requests and for the
    separate connection background audit writes open."""
    import contextlib

    @contextlib.contextmanager
    def fake_hive_cursor():
        yield cursor

    monkeypatch.setattr("app.audit.hive_cursor", fake_hive_cursor)
    monkeypatch.setattr("app.deid.hive_cursor", fake_hive_cursor)

    app.dependency_overrides[get_cursor] = lambda: cursor
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def as_admin(client):
    client.headers.update({"REMOTE-USER": ADMIN_USER})
    return client


@pytest.fixture
def storage_root(tmp_path, monkeypatch):
    """Uploads land in tmp_path, never in the repo's storage/ directory."""
    root = tmp_path / "patient_files"
    monkeypatch.setattr("app.storage.STORAGE_ROOT", root)
    return root


def minimal_patient(**overrides):
    """Only what the API requires: the source document, plus any one of
    fstname / lstname / ptemail. Deliberately omits lstname, so the
    fixture itself exercises the "one identifier is enough" rule."""
    return {"fstname": "Jane", "original_file_path": "/data/jane.pdf", **overrides}


def patient_columns():
    return list(patients_crud.COLUMNS)
