"""The application wizard's own path through the API, end to end."""
from conftest import ADMIN_ID, VIEWER_ID, minimal_patient


def _wizard_patient_payload(**overrides):
    """What PatientForm actually posts: every field, blanks as null."""
    payload = {
        "fstname": "Jane",
        "lstname": "Doe",
        "ptemail": None,
        "instcode": None,
        "pname": None,
        "original_file_path": None,
        "deidentified_file_path": None,
    }
    payload.update(overrides)
    return payload


def test_creating_a_patient_without_a_file_path_is_allowed(as_admin):
    response = as_admin.post("/patients", json=_wizard_patient_payload())
    assert response.status_code == 201, response.text


def test_saving_that_patient_again_is_allowed(as_admin):
    """Step 1 re-submitted: the wizard shows the saved patient and PUTs it
    back. That must not fail on a field the form does not show."""
    created = as_admin.post("/patients", json=_wizard_patient_payload()).json()

    response = as_admin.put(
        f"/patients/{created['id']}", json=_wizard_patient_payload(lstname="Doe-Smith")
    )

    assert response.status_code == 200, response.text


def test_creating_an_application_with_an_assignee(as_admin):
    patient = as_admin.post("/patients", json=minimal_patient()).json()

    response = as_admin.post(
        "/applications",
        json={
            "patient_id": patient["id"],
            "status": "draft",
            "assigned_to_id": VIEWER_ID,
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["assigned_to_id"] == VIEWER_ID


def test_an_applications_folder_is_its_own(as_admin):
    """Two applications for one patient, drawing on different folders --
    which is why this lives on the application and not the patient."""
    patient = as_admin.post("/patients", json=minimal_patient()).json()

    first = as_admin.post(
        "/applications",
        json={"patient_id": patient["id"], "original_file_path": "/data/X"},
    ).json()
    second = as_admin.post(
        "/applications",
        json={"patient_id": patient["id"], "original_file_path": "/data/Y"},
    ).json()

    assert first["original_file_path"] == "/data/X"
    assert second["original_file_path"] == "/data/Y"

    # And neither has disturbed the other.
    assert (
        as_admin.get(f"/applications/{first['id']}").json()["original_file_path"]
        == "/data/X"
    )


def test_an_applications_folder_can_be_changed_afterwards(as_admin):
    patient = as_admin.post("/patients", json=minimal_patient()).json()
    application = as_admin.post(
        "/applications",
        json={"patient_id": patient["id"], "original_file_path": "/data/X"},
    ).json()

    response = as_admin.put(
        f"/applications/{application['id']}", json={"original_file_path": "/data/Y"}
    )

    assert response.status_code == 200, response.text
    assert response.json()["original_file_path"] == "/data/Y"


def test_a_blank_folder_is_stored_as_nothing(as_admin):
    patient = as_admin.post("/patients", json=minimal_patient()).json()

    created = as_admin.post(
        "/applications",
        json={"patient_id": patient["id"], "original_file_path": "   "},
    ).json()

    assert created["original_file_path"] is None


def test_assigning_an_existing_application(as_admin):
    patient = as_admin.post("/patients", json=minimal_patient()).json()
    application = as_admin.post(
        "/applications", json={"patient_id": patient["id"]}
    ).json()

    response = as_admin.put(
        f"/applications/{application['id']}", json={"assigned_to_id": ADMIN_ID}
    )

    assert response.status_code == 200, response.text
    assert response.json()["assigned_to_id"] == ADMIN_ID
