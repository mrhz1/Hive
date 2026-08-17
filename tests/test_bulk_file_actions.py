"""Whole-application actions, for the piles a per-row button cannot clear."""
from conftest import minimal_patient


def _application(client):
    patient_id = client.post("/patients", json=minimal_patient()).json()["id"]
    return client.post("/applications", json={"patient_id": patient_id}).json()["id"]


def _upload(client, application_id, name, data=b"%PDF-1.4 fake"):
    return client.post(
        f"/applications/{application_id}/files",
        files=[("files", (name, data, "application/pdf"))],
    ).json()[0]


# ------------------------------------------------------------- approve all


def test_approve_all_clears_the_undecided_pile(as_admin, storage_root):
    application_id = _application(as_admin)
    for name in ("a.pdf", "b.pdf", "c.pdf"):
        _upload(as_admin, application_id, name)

    response = as_admin.post(f"/applications/{application_id}/files/approve-all")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "total": 3,
        "changed": 3,
        "skipped": 0,
        "reasons": {},
    }

    listed = as_admin.get(f"/applications/{application_id}/files").json()
    assert {record["review_status"] for record in listed} == {"approved"}


def test_approve_all_does_not_overturn_a_rejection(as_admin, storage_root):
    """A bulk approve clears what nobody has looked at. Reversing somebody
    else's rejection is a decision, not a convenience."""
    application_id = _application(as_admin)
    keep = _upload(as_admin, application_id, "a.pdf")
    rejected = _upload(as_admin, application_id, "b.pdf")

    as_admin.post(
        f"/files/{rejected['id']}/review",
        json={"review_status": "rejected", "review_note": "illegible"},
    )

    body = as_admin.post(
        f"/applications/{application_id}/files/approve-all"
    ).json()

    assert body["changed"] == 1
    assert body["reasons"] == {"rejected, left alone": 1}

    by_id = {
        record["id"]: record
        for record in as_admin.get(f"/applications/{application_id}/files").json()
    }
    assert by_id[keep["id"]]["review_status"] == "approved"
    assert by_id[rejected["id"]]["review_status"] == "rejected"


def test_approve_all_is_idempotent(as_admin, storage_root):
    application_id = _application(as_admin)
    _upload(as_admin, application_id, "a.pdf")

    as_admin.post(f"/applications/{application_id}/files/approve-all")
    body = as_admin.post(
        f"/applications/{application_id}/files/approve-all"
    ).json()

    assert body["changed"] == 0
    assert body["reasons"] == {"already approved": 1}


def test_approve_all_on_an_empty_application(as_admin, storage_root):
    application_id = _application(as_admin)

    body = as_admin.post(
        f"/applications/{application_id}/files/approve-all"
    ).json()

    assert body == {"total": 0, "changed": 0, "skipped": 0, "reasons": {}}


# ---------------------------------------------------------- de-identify all


def test_deidentify_all_queues_every_eligible_file(as_admin, storage_root, monkeypatch):
    monkeypatch.setattr(
        "app.routers.patient_application_files.dispatch_deidentification",
        lambda **kwargs: None,
    )

    application_id = _application(as_admin)
    for name in ("a.pdf", "b.pdf"):
        _upload(as_admin, application_id, name)

    response = as_admin.post(
        f"/applications/{application_id}/files/deidentify-all"
    )

    assert response.status_code == 200, response.text
    assert response.json()["changed"] == 2

    listed = as_admin.get(f"/applications/{application_id}/files").json()
    assert {record["deid_status"] for record in listed} == {"processing"}


def test_deidentify_all_skips_what_it_cannot_handle(
    as_admin, storage_root, monkeypatch
):
    monkeypatch.setattr(
        "app.routers.patient_application_files.dispatch_deidentification",
        lambda **kwargs: None,
    )

    application_id = _application(as_admin)
    _upload(as_admin, application_id, "scan.pdf")
    _upload(as_admin, application_id, "notes.txt", data=b"plain text here")

    body = as_admin.post(
        f"/applications/{application_id}/files/deidentify-all"
    ).json()

    assert body["changed"] == 1
    assert body["reasons"] == {"unsupported format": 1}


def test_deidentify_all_does_not_restart_what_is_running(
    as_admin, storage_root, monkeypatch
):
    monkeypatch.setattr(
        "app.routers.patient_application_files.dispatch_deidentification",
        lambda **kwargs: None,
    )

    application_id = _application(as_admin)
    _upload(as_admin, application_id, "a.pdf")

    as_admin.post(f"/applications/{application_id}/files/deidentify-all")
    body = as_admin.post(
        f"/applications/{application_id}/files/deidentify-all"
    ).json()

    assert body["changed"] == 0
    assert body["reasons"] == {"already running": 1}


# ------------------------------------------------------------- permissions


def test_bulk_actions_need_the_update_permission(client, as_admin, storage_root):
    application_id = _application(as_admin)

    client.headers.update({"REMOTE-USER": "viewer"})
    assert (
        client.post(f"/applications/{application_id}/files/approve-all").status_code
        == 403
    )
    assert (
        client.post(
            f"/applications/{application_id}/files/deidentify-all"
        ).status_code
        == 403
    )


def test_bulk_actions_on_an_unknown_application_are_404(as_admin):
    assert as_admin.post("/applications/nope/files/approve-all").status_code == 404
    assert (
        as_admin.post("/applications/nope/files/deidentify-all").status_code == 404
    )


# ---------------------------------------------------- statement economy

def _updates_of(cursor, table):
    """Every UPDATE issued against `table`, as normalised SQL."""
    return [
        sql
        for sql, _ in cursor.statements
        if sql.startswith(f"UPDATE `{table}`")
    ]


def test_approve_all_writes_once_however_many_files(as_admin, storage_root, cursor):
    """The whole reason this endpoint exists is that a per-file loop does not scale.

    update_file is three statements -- an existence check, the UPDATE, and
    a read-back -- so a loop over an application holding a thousand
    documents is three thousand, every UPDATE of them a Hive ACID delta
    write costing seconds. One statement does the same work, and this
    pins that it stays one.
    """
    application_id = _application(as_admin)
    for name in ("a.pdf", "b.pdf", "c.pdf", "d.pdf"):
        _upload(as_admin, application_id, name)

    before = len(_updates_of(cursor, "patient_application_files"))
    response = as_admin.post(f"/applications/{application_id}/files/approve-all")
    assert response.status_code == 200, response.text
    assert response.json()["changed"] == 4

    issued = _updates_of(cursor, "patient_application_files")[before:]
    assert len(issued) == 1, issued
    assert "IN (" in issued[0]


def test_deidentify_all_writes_once_however_many_files(
    as_admin, storage_root, cursor, monkeypatch
):
    monkeypatch.setattr(
        "app.routers.patient_application_files.dispatch_deidentification",
        lambda **kwargs: None,
    )

    application_id = _application(as_admin)
    for name in ("a.pdf", "b.pdf", "c.pdf"):
        _upload(as_admin, application_id, name)

    before = len(_updates_of(cursor, "patient_application_files"))
    response = as_admin.post(f"/applications/{application_id}/files/deidentify-all")
    assert response.status_code == 200, response.text
    assert response.json()["changed"] == 3

    issued = _updates_of(cursor, "patient_application_files")[before:]
    assert len(issued) == 1, issued


def test_nothing_to_do_writes_nothing(as_admin, storage_root, cursor):
    """An empty batch must not issue an UPDATE with an empty IN list."""
    application_id = _application(as_admin)

    before = len(_updates_of(cursor, "patient_application_files"))
    response = as_admin.post(f"/applications/{application_id}/files/approve-all")

    assert response.status_code == 200, response.text
    assert response.json()["changed"] == 0
    assert _updates_of(cursor, "patient_application_files")[before:] == []
