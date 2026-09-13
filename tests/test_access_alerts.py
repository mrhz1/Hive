from datetime import datetime, timezone

import pytest

from scripts import access_alerts


class _Cursor:

    def __init__(self, by_action):
        self.by_action = by_action
        self._result = []
        self.queries = []

    def execute(self, sql, params=()):
        self.queries.append((sql, params))
        action = params[1]
        self._result = self.by_action.get(action, [])

    def fetchall(self):
        return list(self._result)


def _breaches(by_action):
    cursor = _Cursor(by_action)
    return access_alerts.breaches(
        cursor, since=datetime.now(timezone.utc), day_from="2026-02-11"
    )


def test_nothing_to_say_when_everything_is_normal():
    assert _breaches({"download": [("a.reyes", "u1", 3, 2)]}) == []


def test_bulk_identified_downloads_are_raised():
    found = _breaches({"download": [("a.reyes", "u1", 180, 47)]})

    assert len(found) == 1
    assert found[0]["actor"] == "a.reyes"
    assert found[0]["hits"] == 180
    assert found[0]["patients"] == 47


def test_the_export_threshold_is_much_lower_than_the_download_one():
    exports = dict(
        (rule["name"], rule["limit"]) for rule in access_alerts.rules()
    )

    assert exports["metadata exports"] < exports["identified downloads"]


def test_repeated_denials_are_raised():
    found = _breaches({"denied": [("mallory", "u9", 40, 0)]})

    assert found[0]["rule"] == "permission denials"


def test_thresholds_can_be_tuned_without_a_deploy(monkeypatch):
    monkeypatch.setenv("ALERT_DOWNLOAD_LIMIT", "2")

    found = _breaches({"download": [("a.reyes", "u1", 3, 1)]})

    assert found and found[0]["hits"] == 3


def test_a_failing_query_does_not_stop_the_other_rules(monkeypatch):
    class Broken(_Cursor):
        def execute(self, sql, params=()):
            if params[1] == "download":
                raise RuntimeError("hive is down")
            super().execute(sql, params)

    cursor = Broken({"export": [("a.reyes", "u1", 99, 4)]})
    found = access_alerts.breaches(
        cursor, since=datetime.now(timezone.utc), day_from="2026-02-11"
    )

    assert [item["rule"] for item in found] == ["metadata exports"]


def test_the_window_is_pruned_to_partitions():
    cursor = _Cursor({})
    access_alerts.breaches(
        cursor, since=datetime.now(timezone.utc), day_from="2026-02-11"
    )

    sql, params = cursor.queries[0]
    assert "`event_date` >= %s" in sql
    assert params[0] == "2026-02-11"


def test_the_message_names_who_and_how_much():
    body = access_alerts.message(
        [
            {
                "rule": "identified downloads",
                "why": "Bulk retrieval.",
                "actor": "a.reyes",
                "hits": 180,
                "patients": 47,
                "limit": 50,
            }
        ],
        60,
        datetime(2026, 2, 11, 2, 14, tzinfo=timezone.utc),
    )

    assert "a.reyes" in body
    assert "180" in body
    assert "47 distinct patients" in body
    assert "Access log page" in body


@pytest.mark.parametrize(
    "value,expected",
    [
        ("a@x.org, b@x.org", ["a@x.org", "b@x.org"]),
        ("  a@x.org  ", ["a@x.org"]),
        ("", []),
    ],
)
def test_recipients_are_read_from_the_environment(monkeypatch, value, expected):
    monkeypatch.setenv("ALERT_EMAIL_TO", value)

    assert access_alerts.recipients() == expected
