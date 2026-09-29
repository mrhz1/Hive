"""The API behind the Intake page: what arrived, and what needs a person."""

import pytest

from app import intake
from conftest import NOBODY_USER, VIEWER_USER


def _drop(root, relative, data=b"%PDF-1.4 fake"):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


@pytest.fixture
def swept(tmp_path, cursor):
    _drop(tmp_path, "A/B/C/AA1234/image.pdf")
    _drop(tmp_path, "A/B/D/BB0042/BB9999_wrong.pdf", data=b"%PDF-1.4 two")
    _drop(tmp_path, "loose/REPORT_final.pdf", data=b"%PDF-1.4 three")
    _drop(tmp_path, "loose/notes.rtf", data=b"{\\rtf1}")
    intake.sweep(cursor, root=tmp_path, dry_run=False)
    return tmp_path


def test_the_counts_add_up(as_admin, swept):
    counts = as_admin.get("/intake/counts").json()

    assert counts["total"] == 4
    assert counts["queued"] == 1
    assert counts["conflict"] == 1
    assert counts["skipped"] == 2


def test_skipped_files_come_with_the_full_path_and_the_reason(as_admin, swept):
    """Somebody has to go and fix these at source, so they need to find them."""
    rows = as_admin.get("/intake/files", params={"status": "skipped"}).json()

    by_name = {r["file_name"]: r for r in rows}
    assert set(by_name) == {"REPORT_final.pdf", "notes.rtf"}

    report = by_name["REPORT_final.pdf"]
    assert report["source_path"] == str(swept / "loose" / "REPORT_final.pdf")
    assert report["reason"] == intake.NO_PATIENT_CODE
    assert by_name["notes.rtf"]["reason"] == intake.UNSUPPORTED_FORMAT


def test_a_conflict_shows_both_claims(as_admin, swept):
    row = as_admin.get("/intake/files", params={"status": "conflict"}).json()[0]

    assert row["path_code"] == "BB0042"
    assert row["name_code"] == "BB9999"


def test_an_unknown_status_is_refused(as_admin, swept):
    assert as_admin.get("/intake/files", params={"status": "nope"}).status_code == 422


def test_resolving_a_conflict_queues_the_file(as_admin, swept):
    row = as_admin.get("/intake/files", params={"status": "conflict"}).json()[0]

    response = as_admin.post(
        f"/intake/files/{row['id']}/resolve", json={"code": "BB0042"}
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "queued"
    assert response.json()["patient_code"] == "BB0042"
    assert as_admin.get("/intake/files", params={"status": "conflict"}).json() == []


def test_a_code_the_file_never_claimed_is_refused(as_admin, swept):
    row = as_admin.get("/intake/files", params={"status": "conflict"}).json()[0]

    response = as_admin.post(
        f"/intake/files/{row['id']}/resolve", json={"code": "ZZ9999"}
    )

    assert response.status_code == 422
    assert "not one of the codes" in response.text


def test_resolving_is_audited_with_both_claims(as_admin, swept):
    """Whose document this is was decided by a person; that is on record."""
    row = as_admin.get("/intake/files", params={"status": "conflict"}).json()[0]
    as_admin.post(f"/intake/files/{row['id']}/resolve", json={"code": "BB9999"})

    entries = as_admin.get(
        "/logs", params={"entity_type": "intake_file", "entity_id": row["id"]}
    ).json()

    assert entries, "the decision was not audited"
    assert entries[0]["old_values"]["path_code"] == "BB0042"
    assert entries[0]["old_values"]["name_code"] == "BB9999"
    assert entries[0]["new_values"]["patient_code"] == "BB9999"


def test_a_viewer_can_look_but_not_decide(client, swept):
    client.headers.update({"REMOTE-USER": VIEWER_USER})

    assert client.get("/intake/files").status_code == 200

    row = client.get("/intake/files", params={"status": "conflict"}).json()[0]
    response = client.post(f"/intake/files/{row['id']}/resolve", json={"code": "BB0042"})
    assert response.status_code == 403


def test_nobody_sees_anything(client, swept):
    client.headers.update({"REMOTE-USER": NOBODY_USER})

    assert client.get("/intake/files").status_code == 403
    assert client.get("/intake/counts").status_code == 403
