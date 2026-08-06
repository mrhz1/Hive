"""Patient document endpoints.

These are gated on the patients permissions rather than a model of their
own: the files belong to a patient, so reading them is patient:view and
uploading/removing is patient:update.
"""
from conftest import ADMIN_ID, VIEWER_ID, minimal_patient


def _patient(client):
    return client.post("/patients", json=minimal_patient()).json()["id"]


def _upload(client, patient_id, name="scan.pdf", data=b"%PDF-1.4 fake", **kwargs):
    return client.post(
        f"/patients/{patient_id}/files",
        files=[("files", (name, data, "application/pdf"))],
        **kwargs,
    )


def test_upload_lands_under_the_patient(as_admin, storage_root):
    patient_id = _patient(as_admin)

    response = _upload(as_admin, patient_id)
    assert response.status_code == 201, response.text

    record = response.json()[0]
    assert record["patient_id"] == patient_id
    assert record["original_file_name"] == "scan.pdf"
    assert record["file_extension"] == "pdf"
    assert record["file_size"] == len(b"%PDF-1.4 fake")

    # Fresh uploads are not de-identified, and must not claim to be.
    assert record["deid_status"] == "pending"
    assert record["is_deidentified"] is False
    # Nor reviewed -- nobody has looked at it yet.
    assert record["review_status"] == "pending"
    assert record["reviewed_by_id"] is None
    assert record["de_identified_file_path"] is None

    stored = storage_root / patient_id
    assert [p.name for p in stored.iterdir()] == [f"{record['id']}_scan.pdf"]


def test_the_file_row_keeps_its_original_columns(as_admin, storage_root):
    """Renaming the model must not have changed the file schema -- only
    customer_id became patient_id."""
    patient_id = _patient(as_admin)
    record = _upload(as_admin, patient_id).json()[0]

    assert set(record) == {
        "id", "patient_id", "original_file_name", "sanitized_file_name",
        "de_identified_file_name", "file_extension", "mime_type", "file_size",
        "deid_status", "is_deidentified", "created_at", "description",
        "file_path", "de_identified_file_path",
        "review_status", "review_description", "reviewed_by_id", "reviewed_at",
    }


def test_a_folder_upload_sanitises_paths(as_admin, storage_root):
    """webkitRelativePath sends 'sub/dir/x.pdf'; '../' must never be
    honoured against the storage root."""
    patient_id = _patient(as_admin)

    response = as_admin.post(
        f"/patients/{patient_id}/files",
        files=[("files", ("../../etc/passwd.pdf", b"data", "application/pdf"))],
    )
    record = response.json()[0]

    assert record["original_file_name"] == "../../etc/passwd.pdf"
    assert record["sanitized_file_name"] == "passwd.pdf"
    assert (storage_root / patient_id / f"{record['id']}_passwd.pdf").is_file()


def test_listing_is_scoped_to_one_patient(as_admin, storage_root):
    first, second = _patient(as_admin), None
    as_admin.post("/patients", json=minimal_patient(fstname="John"))
    second = as_admin.get("/patients").json()[1]["id"]

    _upload(as_admin, first, name="a.pdf")
    _upload(as_admin, second, name="b.pdf")

    assert [f["original_file_name"] for f in as_admin.get(f"/patients/{first}/files").json()] == ["a.pdf"]
    assert [f["original_file_name"] for f in as_admin.get(f"/patients/{second}/files").json()] == ["b.pdf"]


def test_files_for_an_unknown_patient_are_a_404(as_admin):
    """404 rather than an empty list, so a wrong id is distinguishable
    from a patient with no documents."""
    assert as_admin.get("/patients/nope/files").status_code == 404
    assert _upload(as_admin, "nope").status_code == 404


def test_downloading_serves_the_stored_bytes(as_admin, storage_root):
    patient_id = _patient(as_admin)
    record = _upload(as_admin, patient_id, data=b"%PDF-1.4 hello").json()[0]

    response = as_admin.get(f"/files/{record['id']}/content")
    assert response.status_code == 200
    assert response.content == b"%PDF-1.4 hello"


def test_asking_for_a_redacted_copy_that_does_not_exist(as_admin, storage_root):
    patient_id = _patient(as_admin)
    record = _upload(as_admin, patient_id).json()[0]

    response = as_admin.get(f"/files/{record['id']}/content", params={"deidentified": True})
    assert response.status_code == 422
    assert "not been de-identified" in response.json()["error"]["detail"]


def test_deleting_a_patient_removes_their_documents(as_admin, storage_root):
    patient_id = _patient(as_admin)
    record = _upload(as_admin, patient_id).json()[0]
    on_disk = storage_root / patient_id / f"{record['id']}_scan.pdf"
    assert on_disk.is_file()

    assert as_admin.delete(f"/patients/{patient_id}").status_code == 204

    assert as_admin.get(f"/files/{record['id']}").status_code == 404
    assert not on_disk.exists()


def test_deleting_one_file_removes_its_bytes(as_admin, storage_root):
    patient_id = _patient(as_admin)
    record = _upload(as_admin, patient_id).json()[0]
    on_disk = storage_root / patient_id / f"{record['id']}_scan.pdf"

    assert as_admin.delete(f"/files/{record['id']}").status_code == 204
    assert not on_disk.exists()
    assert as_admin.get(f"/patients/{patient_id}/files").json() == []


def test_deidentify_rejects_a_non_pdf(as_admin, storage_root):
    patient_id = _patient(as_admin)
    record = as_admin.post(
        f"/patients/{patient_id}/files",
        files=[("files", ("notes.txt", b"plain text", "text/plain"))],
    ).json()[0]

    response = as_admin.post(f"/files/{record['id']}/deidentify")
    assert response.status_code == 422
    assert "Only PDF" in response.json()["error"]["detail"]


def test_deidentify_marks_the_row_processing(as_admin, storage_root, monkeypatch):
    """The row is marked before the job starts, so the UI reflects it on
    the very next read."""
    monkeypatch.setattr(
        "app.routers.patient_files.dispatch_deidentification", lambda **kw: None
    )

    patient_id = _patient(as_admin)
    record = _upload(as_admin, patient_id).json()[0]

    response = as_admin.post(f"/files/{record['id']}/deidentify")
    assert response.status_code == 200
    assert response.json()["deid_status"] == "processing"


def test_deidentify_marks_the_row_queued_on_the_job_backend(
    as_admin, storage_root, monkeypatch
):
    """Under DEID_BACKEND=cml_job nothing is processing yet -- a Job run
    has only been asked for. Marking 'processing' here would strand the
    row forever if the run never started, and 'pending' would be
    indistinguishable from a freshly uploaded file."""
    monkeypatch.setattr(
        "app.routers.patient_files.dispatch_deidentification", lambda **kw: None
    )
    monkeypatch.setattr("app.deid.DEID_BACKEND", "cml_job")

    patient_id = _patient(as_admin)
    record = _upload(as_admin, patient_id).json()[0]

    response = as_admin.post(f"/files/{record['id']}/deidentify")
    assert response.status_code == 200
    assert response.json()["deid_status"] == "queued"


def test_deidentify_rejects_a_file_already_in_flight(
    as_admin, storage_root, monkeypatch
):
    """A second click must not start a second run. 'pending' is NOT in
    flight, though -- that is how every file arrives, so a first request
    has to be allowed through."""
    monkeypatch.setattr(
        "app.routers.patient_files.dispatch_deidentification", lambda **kw: None
    )

    patient_id = _patient(as_admin)
    record = _upload(as_admin, patient_id).json()[0]
    assert record["deid_status"] == "pending"

    assert as_admin.post(f"/files/{record['id']}/deidentify").status_code == 200

    second = as_admin.post(f"/files/{record['id']}/deidentify")
    assert second.status_code == 422
    assert "already queued" in second.json()["error"]["detail"]


# ---------------------------------------------------------------- review

def test_approving_a_file_stamps_the_reviewer(as_admin, storage_root):
    patient_id = _patient(as_admin)
    record = _upload(as_admin, patient_id).json()[0]

    response = as_admin.post(
        f"/files/{record['id']}/review", json={"review_status": "approved"}
    )
    assert response.status_code == 200, response.text

    reviewed = response.json()
    assert reviewed["review_status"] == "approved"
    # Attribution comes from the caller's identity, never the request body.
    assert reviewed["reviewed_by_id"] == ADMIN_ID
    assert reviewed["reviewed_at"] is not None


def test_rejecting_a_file_records_the_reason(as_admin, storage_root):
    patient_id = _patient(as_admin)
    record = _upload(as_admin, patient_id).json()[0]

    response = as_admin.post(
        f"/files/{record['id']}/review",
        json={"review_status": "rejected", "review_description": "Page 2 is unreadable"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["review_description"] == "Page 2 is unreadable"


def test_a_rejection_without_a_reason_is_refused(as_admin, storage_root):
    """An approval speaks for itself; a rejection that says nothing leaves
    the uploader with no idea what to fix."""
    patient_id = _patient(as_admin)
    record = _upload(as_admin, patient_id).json()[0]

    for payload in (
        {"review_status": "rejected"},
        {"review_status": "rejected", "review_description": "   "},
    ):
        assert (
            as_admin.post(f"/files/{record['id']}/review", json=payload).status_code
            == 422
        ), payload


def test_review_cannot_be_attributed_by_the_caller(as_admin, storage_root):
    """reviewed_by_id in the body is ignored -- it is not an input."""
    patient_id = _patient(as_admin)
    record = _upload(as_admin, patient_id).json()[0]

    reviewed = as_admin.post(
        f"/files/{record['id']}/review",
        json={"review_status": "approved", "reviewed_by_id": "somebody-else"},
    ).json()

    assert reviewed["reviewed_by_id"] == ADMIN_ID


def test_an_unknown_review_status_is_rejected(as_admin, storage_root):
    patient_id = _patient(as_admin)
    record = _upload(as_admin, patient_id).json()[0]

    response = as_admin.post(
        f"/files/{record['id']}/review", json={"review_status": "maybe"}
    )
    assert response.status_code == 422


def test_reviewing_needs_the_application_permission(client, storage_root):
    """Reviewing a submission is the reviewer's job, not the same grant as
    being allowed to edit patient records."""
    admin = {"X-User-Id": ADMIN_ID}
    patient_id = client.post("/patients", json=minimal_patient(), headers=admin).json()["id"]
    record = _upload(client, patient_id, headers=admin).json()[0]

    client.headers.update({"X-User-Id": VIEWER_ID})
    response = client.post(
        f"/files/{record['id']}/review", json={"review_status": "approved"}
    )
    assert response.status_code == 403
    assert "application:update" in response.json()["error"]["detail"]


def test_empty_uploads_are_skipped_not_fatal(as_admin, storage_root):
    """Picking a folder can yield directory entries and hidden files."""
    patient_id = _patient(as_admin)

    response = as_admin.post(
        f"/patients/{patient_id}/files",
        files=[
            ("files", ("empty", b"", "application/octet-stream")),
            ("files", ("real.pdf", b"%PDF-1.4", "application/pdf")),
        ],
    )
    assert response.status_code == 201
    assert [f["original_file_name"] for f in response.json()] == ["real.pdf"]


def test_file_access_uses_the_patients_permissions(client, storage_root):
    admin = {"X-User-Id": "user-admin"}
    patient_id = client.post("/patients", json=minimal_patient(), headers=admin).json()["id"]
    record = _upload(client, patient_id, headers=admin).json()[0]

    client.headers.update({"X-User-Id": VIEWER_ID})
    # patient:view covers reading documents...
    assert client.get(f"/patients/{patient_id}/files").status_code == 200
    assert client.get(f"/files/{record['id']}").status_code == 200
    # ...but changing them needs patient:update.
    assert _upload(client, patient_id).status_code == 403
    assert client.delete(f"/files/{record['id']}").status_code == 403
    assert client.post(f"/files/{record['id']}/deidentify").status_code == 403
