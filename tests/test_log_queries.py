"""Finding a user's activity, which is where an investigation starts.

Before this the change trail could only be filtered by entity: the actor
was stored and not queryable, so "what did this person do, and when" had
no answer through the application at all.
"""
from conftest import ADMIN_ID, VIEWER_ID, minimal_patient


def _seed_changes(cursor):
    """Two actors, three days, so the filters have something to separate."""
    rows = [
        ("a1", "CREATE", "patient", "P1", ADMIN_ID, "2026-02-10 09:00:00"),
        ("a2", "UPDATE", "patient", "P1", ADMIN_ID, "2026-02-11 09:00:00"),
        ("a3", "DELETE", "patient", "P2", VIEWER_ID, "2026-02-12 09:00:00"),
        ("a4", "UPDATE", "user", "U9", VIEWER_ID, "2026-02-13 09:00:00"),
    ]
    cursor.store["audit_logs"] = [
        {
            "id": i,
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "user_id": user_id,
            "old_values": None,
            "new_values": None,
            "created_at": created_at,
        }
        for i, action, entity_type, entity_id, user_id, created_at in rows
    ]


def test_changes_can_be_filtered_by_who_made_them(as_admin, cursor):
    _seed_changes(cursor)

    found = as_admin.get("/logs", params={"user_id": VIEWER_ID}).json()

    assert {row["id"] for row in found} == {"a3", "a4"}


def test_changes_can_be_filtered_by_date(as_admin, cursor):
    _seed_changes(cursor)

    found = as_admin.get(
        "/logs", params={"date_from": "2026-02-11", "date_to": "2026-02-12"}
    ).json()

    assert {row["id"] for row in found} == {"a2", "a3"}


def test_the_end_of_the_range_includes_that_whole_day(as_admin, cursor):
    """'to 2026-02-12' has to mean the end of the 12th, not its midnight."""
    _seed_changes(cursor)

    found = as_admin.get("/logs", params={"date_to": "2026-02-12"}).json()

    assert "a3" in {row["id"] for row in found}


def test_who_and_when_combine(as_admin, cursor):
    """The incident question: what did this account do in this window."""
    _seed_changes(cursor)

    found = as_admin.get(
        "/logs",
        params={
            "user_id": VIEWER_ID,
            "date_from": "2026-02-13",
            "date_to": "2026-02-13",
        },
    ).json()

    assert {row["id"] for row in found} == {"a4"}


def test_changes_can_be_filtered_by_action(as_admin, cursor):
    _seed_changes(cursor)

    found = as_admin.get("/logs", params={"action": "UPDATE"}).json()

    assert {row["id"] for row in found} == {"a2", "a4"}


def test_the_existing_entity_filters_still_work(as_admin, cursor):
    _seed_changes(cursor)

    found = as_admin.get(
        "/logs", params={"entity_type": "patient", "entity_id": "P1"}
    ).json()

    assert {row["id"] for row in found} == {"a1", "a2"}


# ------------------------------------------------------- the access trail


def test_the_access_trail_answers_who_saw_this_patient(
    as_admin, storage_root, access_events
):
    """Disclosure accounting, which has no answer without this."""
    patient_id = as_admin.post("/patients", json=minimal_patient()).json()["id"]
    application_id = as_admin.post(
        "/applications", json={"patient_id": patient_id}
    ).json()["id"]
    record = as_admin.post(
        f"/applications/{application_id}/files",
        files=[("files", ("scan.pdf", b"%PDF-1.4 fake", "application/pdf"))],
    ).json()[0]

    as_admin.get(f"/files/{record['id']}/content")
    access_events.flush()

    found = as_admin.get("/access-logs", params={"patient_id": patient_id}).json()

    assert [row["action"] for row in found] == ["download"]
    assert found[0]["actor_username"] == "admin"
    assert found[0]["identified"] is True


def test_the_access_trail_can_be_narrowed_to_disclosures(
    as_admin, storage_root, access_events
):
    """Reading a redacted copy is routine; the identified reads are the
    ones a breach assessment counts."""
    patient_id = as_admin.post("/patients", json=minimal_patient()).json()["id"]
    as_admin.get(f"/patients/{patient_id}")
    access_events.flush()

    found = as_admin.get("/access-logs", params={"identified_only": True}).json()

    assert found and all(row["identified"] for row in found)


def test_the_access_trail_needs_the_log_permission(client, access_events):
    client.headers.update({"REMOTE-USER": "nobody"})

    assert client.get("/access-logs").status_code == 403


def test_a_bounded_query_reads_only_those_partitions(as_admin, cursor):
    """The date filter has to select partitions, or a year of events is
    scanned to answer a question about one week."""
    as_admin.get(
        "/access-logs", params={"date_from": "2026-02-01", "date_to": "2026-02-07"}
    )

    sql = [s for s, _ in cursor.statements if "FROM `access_logs`" in s][-1]

    assert "`event_date` >= %s" in sql
    assert "`event_date` <= %s" in sql
