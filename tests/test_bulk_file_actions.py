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


def _reviewable(client, application_id, name):
    """An uploaded file with a redacted copy, so a verdict is allowed.

    Approve-all skips anything not de-identified yet -- there is nothing
    to review until the redacted copy exists. Tests about the approving
    itself start past that.
    """
    record = _upload(client, application_id, name)
    client.put(f"/files/{record['id']}", json={"is_deidentified": True})
    return record


# ------------------------------------------------------------- approve all


def test_approve_all_clears_the_undecided_pile(as_admin, storage_root):
    application_id = _application(as_admin)
    for name in ("a.pdf", "b.pdf", "c.pdf"):
        _reviewable(as_admin, application_id, name)

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
    keep = _reviewable(as_admin, application_id, "a.pdf")
    rejected = _reviewable(as_admin, application_id, "b.pdf")

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
    _reviewable(as_admin, application_id, "a.pdf")

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


# ------------------------------------- nothing is reviewable before redaction

def test_approve_all_skips_what_has_not_been_de_identified(as_admin, storage_root):
    """A verdict is a verdict on the redacted copy.

    Without this the bulk button would approve in one click exactly what
    the per-file action refuses -- and an application could be signed off
    with documents still carrying their identifiers.
    """
    application_id = _application(as_admin)
    ready = _reviewable(as_admin, application_id, "done.pdf")
    _upload(as_admin, application_id, "waiting.pdf")

    body = as_admin.post(
        f"/applications/{application_id}/files/approve-all"
    ).json()

    assert body["changed"] == 1
    assert body["reasons"] == {"not de-identified yet": 1}

    by_id = {
        record["id"]: record
        for record in as_admin.get(f"/applications/{application_id}/files").json()
    }
    assert by_id[ready["id"]]["review_status"] == "approved"
    assert all(
        record["review_status"] == "pending"
        for record in by_id.values()
        if record["id"] != ready["id"]
    )


def test_a_file_cannot_be_approved_before_it_is_de_identified(
    as_admin, storage_root
):
    application_id = _application(as_admin)
    record = _upload(as_admin, application_id, "waiting.pdf")

    response = as_admin.post(
        f"/files/{record['id']}/review", json={"review_status": "approved"}
    )

    assert response.status_code == 422, response.text
    assert "not been de-identified" in response.json()["error"]["detail"]


def test_a_file_cannot_be_rejected_before_it_is_de_identified(
    as_admin, storage_root
):
    """Rejecting is a verdict too, and there is still nothing to look at."""
    application_id = _application(as_admin)
    record = _upload(as_admin, application_id, "waiting.pdf")

    response = as_admin.post(
        f"/files/{record['id']}/review",
        json={"review_status": "rejected", "review_note": "illegible"},
    )

    assert response.status_code == 422, response.text
    assert "not been de-identified" in response.json()["error"]["detail"]
