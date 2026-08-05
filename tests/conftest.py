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

# --------------------------------------------------------------- fixtures

ADMIN_ID = "user-admin"
VIEWER_ID = "user-viewer"
NOBODY_ID = "user-nobody"

ALL_PERMISSIONS = [
    f"{model}:{action}"
    for model in ("users", "patients", "roles", "logs")
    for action in ("read", "create", "update", "delete")
]
READONLY_PERMISSIONS = [f"{m}:read" for m in ("users", "patients", "roles", "logs")]


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
        "patients": [],
        "patient_files": [],
        "audit_log": [],
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
_INSERT = re.compile(r"^INSERT INTO `(?P<table>\w+)` \((?P<cols>.+?)\) VALUES", re.S)
_UPDATE = re.compile(r"^UPDATE `(?P<table>\w+)` SET (?P<sets>.+?) WHERE `(?P<key>\w+)` = %s$", re.S)
_DELETE = re.compile(r"^DELETE FROM `(?P<table>\w+)` WHERE `(?P<key>\w+)` = %s$", re.S)
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
        assert len(columns) == len(params), (
            f"INSERT into `{match.group('table')}` binds {len(params)} params "
            f"for {len(columns)} columns"
        )
        self._rows(match.group("table")).append(dict(zip(columns, params)))
        return []

    def _update(self, sql, params):
        match = _UPDATE.match(sql)
        assert match, f"unparsed UPDATE: {sql}"
        columns = _COL.findall(match.group("sets"))
        values, key = params[:-1], params[-1]
        assert len(columns) == len(values), "UPDATE arity mismatch"

        for row in self._rows(match.group("table")):
            if row.get(match.group("key")) == key:
                row.update(dict(zip(columns, values)))
        return []

    def _delete(self, sql, params):
        match = _DELETE.match(sql)
        assert match, f"unparsed DELETE: {sql}"
        table, key = match.group("table"), match.group("key")
        self.store[table] = [r for r in self._rows(table) if r.get(key) != params[0]]
        return []


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
    client.headers.update({"X-User-Id": ADMIN_ID})
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
