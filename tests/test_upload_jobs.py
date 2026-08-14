"""Background upload batches, and who hears about them."""
import pathlib
import re

import pytest
from conftest import ADMIN_ID, VIEWER_ID, minimal_patient

from app import uploads

# <patient id>-<document type>-<16-digit serial>.<ext>
DOCUMENT = re.compile(r"^[A-Z0-9]{6}-[a-z0-9]+-\d{16}\.[a-z0-9]+$")


def _patient_and_application(client, assigned_to_id=None):
    patient_id = client.post("/patients", json=minimal_patient()).json()["id"]
    payload = {"patient_id": patient_id}
    if assigned_to_id is not None:
        payload["assigned_to_id"] = assigned_to_id
    application_id = client.post("/applications", json=payload).json()["id"]
    return patient_id, application_id


def _upload(client, application_id, files=None, **kwargs):
    files = files or [("files", ("scan.pdf", b"%PDF-1.4 fake", "application/pdf"))]
    return client.post(
        f"/applications/{application_id}/files/background", files=files, **kwargs
    )


# TestClient runs background tasks before it hands the response back, so a
# job is always finished by the time these assertions run.


def test_the_batch_is_accepted_before_it_is_stored(as_admin, storage_root, sent_emails):
    _, application_id = _patient_and_application(as_admin)

    response = _upload(as_admin, application_id)
    assert response.status_code == 202, response.text

    job = response.json()
    assert job["application_id"] == application_id
    assert job["total"] == 1
    assert [entry["name"] for entry in job["files"]] == ["scan.pdf"]


def test_the_files_land_where_the_synchronous_upload_puts_them(
    as_admin, storage_root, sent_emails
):
    patient_id, application_id = _patient_and_application(as_admin)

    job_id = _upload(as_admin, application_id).json()["id"]

    job = as_admin.get(f"/upload-jobs/{job_id}").json()
    assert job["status"] == "done"
    assert job["stored"] == 1
    assert job["failed"] == 0

    listed = as_admin.get(f"/applications/{application_id}/files").json()
    assert len(listed) == 1
    assert listed[0]["original_file_name"] == "scan.pdf"

    stored = pathlib.Path(listed[0]["file_path"])
    assert stored.is_file()
    assert DOCUMENT.match(stored.name), stored.name
    assert stored.parent.name.startswith(f"{patient_id}-")

    # The wizard records this against the patient as their source folder.
    assert job["folder"] == str(stored.parent)


def test_staging_is_cleaned_up_afterwards(as_admin, storage_root, sent_emails):
    _, application_id = _patient_and_application(as_admin)

    job_id = _upload(as_admin, application_id).json()["id"]

    assert not uploads.staging_dir(job_id).exists()


def test_metadata_is_extracted_for_a_backgrounded_file(
    as_admin, storage_root, sent_emails
):
    _, application_id = _patient_and_application(as_admin)

    _upload(as_admin, application_id)

    file_id = as_admin.get(f"/applications/{application_id}/files").json()[0]["id"]
    assert as_admin.get(f"/files/{file_id}/metadata").status_code == 200


def test_the_assigned_user_is_told_when_the_batch_is_done(
    as_admin, storage_root, sent_emails
):
    _, application_id = _patient_and_application(as_admin, assigned_to_id=VIEWER_ID)

    _upload(as_admin, application_id)

    assert len(sent_emails) == 1
    assert sent_emails[0]["to"] == ["viewer@example.com"]
    assert "1 file" in sent_emails[0]["subject"]


def test_an_unassigned_batch_falls_back_to_whoever_uploaded_it(
    as_admin, storage_root, sent_emails
):
    _, application_id = _patient_and_application(as_admin)

    _upload(as_admin, application_id)

    assert [mail["to"] for mail in sent_emails] == [["admin@example.com"]]


def test_a_file_that_cannot_be_stored_emails_the_assigned_user(
    as_admin, storage_root, sent_emails, monkeypatch
):
    _, application_id = _patient_and_application(as_admin, assigned_to_id=VIEWER_ID)

    def explode(*_args, **_kwargs):
        raise OSError("the volume went away")

    monkeypatch.setattr(uploads, "move_patient_document", explode)

    job_id = _upload(as_admin, application_id).json()["id"]

    job = as_admin.get(f"/upload-jobs/{job_id}").json()
    assert job["status"] == "failed"
    assert job["failed"] == 1
    assert job["files"][0]["error"] == "the volume went away"

    assert len(sent_emails) == 1
    assert sent_emails[0]["to"] == ["viewer@example.com"]
    assert "failed" in sent_emails[0]["subject"].lower()
    assert "the volume went away" in sent_emails[0]["body"]

    # Nothing half-recorded: a file that never moved has no row either.
    assert as_admin.get(f"/applications/{application_id}/files").json() == []


def test_one_bad_file_does_not_cost_the_rest_of_the_batch(
    as_admin, storage_root, sent_emails, monkeypatch
):
    _, application_id = _patient_and_application(as_admin, assigned_to_id=VIEWER_ID)

    real_move = uploads.move_patient_document
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("bad sector")
        return real_move(*args, **kwargs)

    monkeypatch.setattr(uploads, "move_patient_document", flaky)

    job_id = _upload(
        as_admin,
        application_id,
        files=[
            ("files", ("first.pdf", b"%PDF-1.4 one", "application/pdf")),
            ("files", ("second.pdf", b"%PDF-1.4 two", "application/pdf")),
        ],
    ).json()["id"]

    job = as_admin.get(f"/upload-jobs/{job_id}").json()
    assert job["status"] == "partial"
    assert (job["stored"], job["failed"]) == (1, 1)

    listed = as_admin.get(f"/applications/{application_id}/files").json()
    assert [record["original_file_name"] for record in listed] == ["second.pdf"]

    assert "partly failed" in sent_emails[0]["subject"]


def test_empty_files_are_skipped_and_an_empty_batch_is_rejected(
    as_admin, storage_root, sent_emails
):
    _, application_id = _patient_and_application(as_admin)

    response = _upload(
        as_admin,
        application_id,
        files=[("files", ("empty.pdf", b"", "application/pdf"))],
    )
    assert response.status_code == 422
    assert not sent_emails


def test_an_unknown_job_is_a_404(as_admin):
    assert as_admin.get("/upload-jobs/nope").status_code == 404


def test_uploading_in_the_background_needs_the_update_permission(
    client, storage_root, sent_emails
):
    client.headers.update({"REMOTE-USER": "admin"})
    _, application_id = _patient_and_application(client)

    client.headers.update({"REMOTE-USER": "viewer"})
    assert _upload(client, application_id).status_code == 403


@pytest.mark.parametrize("assignee", [ADMIN_ID, None])
def test_assignment_survives_a_round_trip(as_admin, assignee):
    _, application_id = _patient_and_application(as_admin, assigned_to_id=assignee)

    fetched = as_admin.get(f"/applications/{application_id}").json()
    assert fetched["assigned_to_id"] == assignee


def test_the_email_links_to_the_application(
    as_admin, storage_root, sent_emails, monkeypatch
):
    """An id alone means opening the dashboard, finding the list and
    searching for eight characters of a uuid."""
    monkeypatch.setenv("APP_BASE_URL", "https://patients.example.org/")
    _, application_id = _patient_and_application(as_admin, assigned_to_id=VIEWER_ID)

    _upload(as_admin, application_id)

    body = sent_emails[0]["body"]
    # The trailing slash on the setting must not become a double one.
    assert f"https://patients.example.org/applications/{application_id}" in body


def test_without_a_configured_address_the_email_still_names_the_application(
    as_admin, storage_root, sent_emails, monkeypatch
):
    monkeypatch.delenv("APP_BASE_URL", raising=False)
    _, application_id = _patient_and_application(as_admin, assigned_to_id=VIEWER_ID)

    _upload(as_admin, application_id)

    body = sent_emails[0]["body"]
    assert application_id in body
    assert "http" not in body


def test_the_email_says_where_the_files_actually_went(
    as_admin, storage_root, sent_emails
):
    """'Which samples folder?' is the question a bare folder name invites."""
    _, application_id = _patient_and_application(as_admin, assigned_to_id=VIEWER_ID)

    _upload(as_admin, application_id)

    body = sent_emails[0]["body"]
    assert "Stored in: " in body
    assert str(storage_root) in body
