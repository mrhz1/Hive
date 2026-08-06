"""Patient application endpoints, end to end through permissions ->
router -> CRUD.

Applications carry their own `application:*` grants rather than reusing
the patient ones: reviewing a submission is a different job from editing
the clinical record.
"""
from conftest import ADMIN_ID, NOBODY_ID, VIEWER_ID, minimal_patient


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
    """Hive enforces no foreign keys, so nothing but this check stops a
    row pointing at a patient that does not exist."""
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
    """Only the transition stamps the actor. Otherwise the trail degrades
    into whoever touched the row last."""
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
    """created_by_id is not an input -- it comes from the authenticated
    caller, so a forged body is ignored rather than honoured."""
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


def test_delete_removes_it(as_admin):
    created = _application(as_admin, _patient(as_admin)).json()

    assert as_admin.delete(f"/applications/{created['id']}").status_code == 204
    assert as_admin.get("/applications").json() == []


def test_deleting_a_patient_removes_their_applications(as_admin):
    """Nothing else would: Hive has no cascading delete."""
    patient_id = _patient(as_admin)
    _application(as_admin, patient_id)

    assert as_admin.delete(f"/patients/{patient_id}").status_code == 204
    assert as_admin.get("/applications").json() == []


# ----------------------------------------------------------- permissions

def test_reader_cannot_write(client):
    client.headers.update({"X-User-Id": VIEWER_ID})
    patient_id = "some-patient"

    assert client.get("/applications").status_code == 200
    assert client.post("/applications", json={"patient_id": patient_id}).status_code == 403
    assert client.put("/applications/x", json={"status": "draft"}).status_code == 403
    assert client.delete("/applications/x").status_code == 403


def test_a_role_with_no_grants_is_locked_out(client):
    client.headers.update({"X-User-Id": NOBODY_ID})
    response = client.get("/applications")
    assert response.status_code == 403
    assert "application:view" in response.json()["error"]["detail"]


def test_identity_is_required(client):
    assert client.get("/applications").status_code == 401


# ---------------------------------------------------------------- audit

def test_writes_are_audited_as_patient_application(as_admin, store):
    created = _application(as_admin, _patient(as_admin)).json()
    as_admin.put(f"/applications/{created['id']}", json={"status": "submitted"})
    as_admin.delete(f"/applications/{created['id']}")

    entries = [
        e for e in store["audit_logs"] if e["entity_type"] == "patient_application"
    ]
    assert [e["action"] for e in entries] == ["CREATE", "UPDATE", "DELETE"]
    assert all(e["entity_id"] == created["id"] for e in entries)
