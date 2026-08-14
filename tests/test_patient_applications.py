"""Patient application endpoints, end to end through permissions -> router -> CRUD."""
from conftest import ADMIN_ID, NOBODY_USER, VIEWER_USER, minimal_patient


def _patient(client):
    return client.post("/patients", json=minimal_patient()).json()["id"]


def _application(client, patient_id, **overrides):
    return client.post(
        "/applications", json={"patient_id": patient_id, **overrides}
    )


# ------------------------------------------------------------ the shape

def test_model_exposes_every_requested_field(as_admin):
    created = _application(as_admin, _patient(as_admin)).json()

    assert set(created) == {
        "id", "patient_id", "submitted_by_id", "reviewed_by_id", "status",
        "description", "created_by_id", "updated_by_id",
        "submitted_at", "created_at", "updated_at", "reviewed_at",
        "status_reason", "assigned_to_id", "original_file_path",
    }


def test_a_new_application_is_a_draft_stamped_with_its_creator(as_admin):
    created = _application(as_admin, _patient(as_admin)).json()

    assert created["status"] == "draft"
    assert created["created_by_id"] == ADMIN_ID
    assert created["updated_by_id"] == ADMIN_ID
    assert created["created_at"] is not None
    # A draft has not been submitted or reviewed by anyone yet.
    assert created["submitted_by_id"] is None
    assert created["submitted_at"] is None
    assert created["reviewed_by_id"] is None
    assert created["reviewed_at"] is None


def test_an_application_for_an_unknown_patient_is_a_404(as_admin):
    """Hive enforces no foreign keys, so nothing but this check stops a row pointing at a patient that does not exist."""
    assert _application(as_admin, "no-such-patient").status_code == 404


def test_an_unknown_status_is_rejected(as_admin):
    response = _application(as_admin, _patient(as_admin), status="whenever")
    assert response.status_code == 422


# ----------------------------------------------------------- transitions

def test_submitting_stamps_the_submitter(as_admin):
    created = _application(as_admin, _patient(as_admin)).json()

    submitted = as_admin.put(
        f"/applications/{created['id']}", json={"status": "submitted"}
    ).json()

    assert submitted["status"] == "submitted"
    assert submitted["submitted_by_id"] == ADMIN_ID
    assert submitted["submitted_at"] is not None
    # Submitting is not reviewing.
    assert submitted["reviewed_by_id"] is None


def test_reviewing_stamps_the_reviewer(as_admin):
    created = _application(as_admin, _patient(as_admin)).json()
    as_admin.put(f"/applications/{created['id']}", json={"status": "submitted"})

    reviewed = as_admin.put(
        f"/applications/{created['id']}", json={"status": "approved"}
    ).json()

    assert reviewed["status"] == "approved"
    assert reviewed["reviewed_by_id"] == ADMIN_ID
    assert reviewed["reviewed_at"] is not None


def test_resaving_does_not_rewrite_who_submitted_it(as_admin):
    """Only the transition stamps the actor."""
    created = _application(as_admin, _patient(as_admin)).json()
    first = as_admin.put(
        f"/applications/{created['id']}", json={"status": "submitted"}
    ).json()

    again = as_admin.put(
        f"/applications/{created['id']}",
        json={"status": "submitted", "description": "resaved"},
    ).json()

    assert again["submitted_at"] == first["submitted_at"]


def test_every_write_records_who_made_it(as_admin):
    created = _application(as_admin, _patient(as_admin)).json()

    updated = as_admin.put(
        f"/applications/{created['id']}", json={"description": "note"}
    ).json()

    assert updated["updated_by_id"] == ADMIN_ID
    assert updated["updated_at"] is not None


def test_the_caller_cannot_attribute_an_application_to_someone_else(as_admin):
    """created_by_id is not an input -- it comes from the authenticated caller, so a forged body is ignored rather than honoured."""
    created = _application(
        as_admin, _patient(as_admin), created_by_id="somebody-else"
    ).json()

    assert created["created_by_id"] == ADMIN_ID


# ------------------------------------------------------------- lifecycle

def test_list_filters_by_patient(as_admin):
    first, second = _patient(as_admin), _patient(as_admin)
    _application(as_admin, first)
    _application(as_admin, first)
    _application(as_admin, second)

    assert len(as_admin.get("/applications").json()) == 3
    assert len(as_admin.get("/applications", params={"patient_id": first}).json()) == 2


def test_unknown_application_is_a_404(as_admin):
    assert as_admin.get("/applications/nope").status_code == 404
    assert as_admin.put("/applications/nope", json={"status": "draft"}).status_code == 404
    assert as_admin.delete("/applications/nope").status_code == 404


def test_delete_keeps_the_record_and_says_why(as_admin):
    """The documents go; the application stays."""
    created = _application(as_admin, _patient(as_admin)).json()

    response = as_admin.delete(
        f"/applications/{created['id']}", params={"reason": "duplicate submission"}
    )

    assert response.status_code == 204

    remaining = as_admin.get("/applications").json()
    assert len(remaining) == 1
    assert remaining[0]["id"] == created["id"]
    assert remaining[0]["status"] == "deleted"
    assert remaining[0]["status_reason"] == "duplicate submission"


def test_delete_requires_a_reason(as_admin):
    created = _application(as_admin, _patient(as_admin)).json()

    for params in ({}, {"reason": "   "}):
        response = as_admin.delete(f"/applications/{created['id']}", params=params)
        assert response.status_code == 422, params
        assert "reason is required" in response.json()["error"]["detail"]

    assert as_admin.get(f"/applications/{created['id']}").json()["status"] == "draft"


def test_deleting_removes_the_documents(as_admin, storage_root):
    import pathlib

    patient_id = _patient(as_admin)
    application_id = _application(as_admin, patient_id).json()["id"]
    record = as_admin.post(
        f"/applications/{application_id}/files",
        files=[("files", ("scan.pdf", b"%PDF-1.4 fake", "application/pdf"))],
    ).json()[0]
    on_disk = pathlib.Path(record["file_path"])
    assert on_disk.is_file()

    as_admin.delete(
        f"/applications/{application_id}", params={"reason": "wrong patient"}
    )

    assert not on_disk.exists(), "the document survived the delete"
    assert as_admin.get(f"/files/{record['id']}").status_code == 404


# ------------------------------------------------------------- rejection


def test_rejecting_records_the_reason(as_admin):
    created = _application(as_admin, _patient(as_admin)).json()

    response = as_admin.post(
        f"/applications/{created['id']}/reject", json={"reason": "missing consent"}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert response.json()["status_reason"] == "missing consent"


def test_rejecting_needs_a_reason(as_admin):
    created = _application(as_admin, _patient(as_admin)).json()

    response = as_admin.post(f"/applications/{created['id']}/reject", json={})

    assert response.status_code == 422
    assert "reason is required" in response.json()["error"]["detail"]


def test_a_submitted_application_cannot_be_rejected(as_admin):
    """Explicitly asked for: once submitted it has gone for review, and the verdict is not recorded from here."""
    created = _application(as_admin, _patient(as_admin)).json()
    as_admin.put(f"/applications/{created['id']}", json={"status": "submitted"})

    response = as_admin.post(
        f"/applications/{created['id']}/reject", json={"reason": "no"}
    )

    assert response.status_code == 422
    assert "cannot be rejected" in response.json()["error"]["detail"]
    assert as_admin.get(f"/applications/{created['id']}").json()["status"] == "submitted"


def test_an_approved_application_can_still_be_rejected(as_admin):
    created = _application(as_admin, _patient(as_admin)).json()
    as_admin.put(f"/applications/{created['id']}", json={"status": "approved"})

    response = as_admin.post(
        f"/applications/{created['id']}/reject", json={"reason": "reviewed again"}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"


def test_rejecting_twice_is_refused(as_admin):
    created = _application(as_admin, _patient(as_admin)).json()
    as_admin.post(f"/applications/{created['id']}/reject", json={"reason": "first"})

    response = as_admin.post(
        f"/applications/{created['id']}/reject", json={"reason": "second"}
    )

    assert response.status_code == 422
    assert as_admin.get(f"/applications/{created['id']}").json()[
        "status_reason"
    ] == "first"


def test_a_patient_with_an_application_cannot_be_deleted(as_admin):
    """Deleting a patient used to take their applications with them,
    which is the one thing the soft delete exists to prevent: an
    application is *kept* when it is deleted, as the record of what
    happened to it. So the patient stays while anything refers to them."""
    patient_id = _patient(as_admin)
    application_id = _application(as_admin, patient_id).json()["id"]

    refused = as_admin.delete(f"/patients/{patient_id}")

    assert refused.status_code == 409
    assert "application" in refused.json()["error"]["detail"]

    # Neither end of it was touched.
    assert as_admin.get(f"/patients/{patient_id}").status_code == 200
    assert as_admin.get(f"/applications/{application_id}").status_code == 200


def test_an_application_that_was_deleted_still_holds_the_patient(as_admin):
    """It is marked deleted, not removed -- the row is still there and
    still names the patient, so the patient is still spoken for."""
    patient_id = _patient(as_admin)
    application_id = _application(as_admin, patient_id).json()["id"]

    as_admin.request(
        "DELETE",
        f"/applications/{application_id}",
        json={"reason": "filed against the wrong patient"},
    )

    refused = as_admin.delete(f"/patients/{patient_id}")

    assert refused.status_code == 409
    assert as_admin.get(f"/patients/{patient_id}").status_code == 200


def test_a_patient_with_no_applications_is_deleted(as_admin):
    patient_id = _patient(as_admin)

    assert as_admin.delete(f"/patients/{patient_id}").status_code == 204
    assert as_admin.get(f"/patients/{patient_id}").status_code == 404


# ----------------------------------------------------------- permissions

def test_reader_cannot_write(client):
    client.headers.update({"REMOTE-USER": VIEWER_USER})
    patient_id = "some-patient"

    assert client.get("/applications").status_code == 200
    assert client.post("/applications", json={"patient_id": patient_id}).status_code == 403
    assert client.put("/applications/x", json={"status": "draft"}).status_code == 403
    assert client.delete("/applications/x").status_code == 403


def test_a_role_with_no_grants_is_locked_out(client):
    client.headers.update({"REMOTE-USER": NOBODY_USER})
    response = client.get("/applications")
    assert response.status_code == 403
    assert "application:view" in response.json()["error"]["detail"]


def test_identity_is_required(client):
    assert client.get("/applications").status_code == 401


# ---------------------------------------------------------------- audit

def test_writes_are_audited_as_patient_application(as_admin, store):
    created = _application(as_admin, _patient(as_admin)).json()
    as_admin.put(f"/applications/{created['id']}", json={"status": "submitted"})
    as_admin.delete(
        f"/applications/{created['id']}", params={"reason": "test cleanup"}
    )

    entries = [
        e for e in store["audit_logs"] if e["entity_type"] == "patient_application"
    ]
    assert [e["action"] for e in entries] == ["CREATE", "UPDATE", "DELETE"]
    assert all(e["entity_id"] == created["id"] for e in entries)
