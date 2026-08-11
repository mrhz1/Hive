"""Test harness: an in-memory stand-in for HiveServer2."""
import json
import re
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from app.crud import patients as patients_crud
from app.db import get_cursor
from app.main import app
from app.security import KNOWN_PERMISSIONS, MODEL_ACTIONS

# --------------------------------------------------------------- fixtures

ADMIN_ID = "user-admin"
VIEWER_ID = "user-viewer"
NOBODY_ID = "user-nobody"

ADMIN_USER = "admin"
VIEWER_USER = "viewer"
NOBODY_USER = "nobody"

ALL_PERMISSIONS = sorted(KNOWN_PERMISSIONS)

# The read grant for each model, whatever it happens to be called there.
READONLY_PERMISSIONS = [
    f"{model}:{'read' if 'read' in actions else 'view'}"
    for model, actions in MODEL_ACTIONS.items()
]


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
        "access_logs": [],
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
# The access trail writes batches into a dated partition, so its INSERT
# has a shape the plain one above cannot parse:
#   INSERT INTO TABLE `t` PARTITION (`event_date` = %s) (cols) VALUES (..), (..)
_INSERT_PARTITIONED = re.compile(
    r"^INSERT INTO TABLE `(?P<table>\w+)` "
    r"PARTITION \(`(?P<part>\w+)` = %s\) \((?P<cols>.+?)\) VALUES (?P<rows>.+)$",
    re.S,
)
_UPDATE = re.compile(r"^UPDATE `(?P<table>\w+)` SET (?P<sets>.+?) WHERE `(?P<key>\w+)` = %s$", re.S)
_DELETE = re.compile(r"^DELETE FROM `(?P<table>\w+)` WHERE `(?P<key>\w+)` = %s$", re.S)
_DELETE_IN = re.compile(r"^DELETE FROM `(?P<table>\w+)` WHERE `(?P<key>\w+)` IN \((?P<slots>[%s, ]+)\)$", re.S)
# Comparisons, not just equality: the log filters bound by date, and a
# pattern that only matched `= %s` would skip those clauses while still
# consuming their parameters -- silently comparing the wrong values.
_WHERE = re.compile(r"`(?P<col>\w+)` (?P<op>=|>=|<=|<|>) %s")
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
            rows = _compare(rows, where.group("col"), where.group("op"), wanted)

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
        partitioned = _INSERT_PARTITIONED.match(sql)
        if partitioned:
            return self._insert_partitioned(partitioned, params)

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

    def _insert_partitioned(self, match, params):
        """A batched INSERT into one partition -- the access trail's shape.

        The partition value is the first bound parameter, then one group
        of placeholders per row, in column order.
        """
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


def _compare(rows, column, op, wanted):
    """One WHERE clause, applied the way Hive would."""
    if op == "=":
        return [r for r in rows if r.get(column) == wanted]

    def key(row):
        # Timestamps arrive as datetimes and bounds as strings.
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
    """Split a VALUES list or SET clause on its top-level commas."""
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
    """One value expression, resolved to what Hive would store."""
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
    """Values as the driver would hand them back."""
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
    """TestClient with Hive replaced by the fake, for requests and for the separate connection background audit writes open."""
    import contextlib

    @contextlib.contextmanager
    def fake_hive_cursor():
        yield cursor

    monkeypatch.setattr("app.audit.hive_cursor", fake_hive_cursor)
    monkeypatch.setattr("app.deid.hive_cursor", fake_hive_cursor)
    monkeypatch.setattr("app.submission.hive_cursor", fake_hive_cursor)
    monkeypatch.setattr("app.uploads.hive_cursor", fake_hive_cursor)
    monkeypatch.setattr("app.access_log.hive_cursor", fake_hive_cursor)

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


@pytest.fixture
def access_events(cursor, monkeypatch):
    """Access events, written on demand instead of on a timer.

    The real writer flushes from a background thread every few seconds,
    which a test outruns. Holding the thread back and flushing by hand
    exercises the same enqueue and INSERT path, deterministically.
    """
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

    # Anything a previous test left queued would land in this store.
    while True:
        try:
            access_log._queue.get_nowait()
        except Exception:
            break

    return Events()


@pytest.fixture
def sent_emails(monkeypatch):
    """Every notification the code tried to send, instead of an SMTP socket."""
    outbox = []

    def fake_send(to, subject, body, html=None):
        recipients = [address for address in to if address]
        if not recipients:
            return False
        outbox.append({"to": recipients, "subject": subject, "body": body})
        return True

    monkeypatch.setattr("app.notifications.send_email", fake_send)
    return outbox


def minimal_patient(**overrides):
    """Only what the API requires: the source document, plus any one of fstname / lstname / ptemail."""
    return {"fstname": "Jane", "original_file_path": "/data/jane.pdf", **overrides}


def patient_columns():
    return list(patients_crud.COLUMNS)
