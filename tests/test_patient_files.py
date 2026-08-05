"""Patient document endpoints.

These are gated on the patients permissions rather than a model of their
own: the files belong to a patient, so reading them is patients:read and
uploading/removing is patients:update.
"""
from conftest import VIEWER_ID, minimal_patient


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
    assert record["is_identified"] is True
    assert record["deidentified_file_path"] is None

    stored = storage_root / patient_id
    assert [p.name for p in stored.iterdir()] == [f"{record['id']}_scan.pdf"]


def test_the_file_row_keeps_its_original_columns(as_admin, storage_root):
    """Renaming the model must not have changed the file schema -- only
    customer_id became patient_id."""
    patient_id = _patient(as_admin)
    record = _upload(as_admin, patient_id).json()[0]

    assert set(record) == {
        "id", "patient_id", "original_file_name", "sanitized_file_name",
        "deidentified_file_name", "file_extension", "mime_type", "file_size",
        "deid_status", "is_identified", "created_at", "description",
        "file_path", "deidentified_file_path",
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
    monkeypatch.setattr("app.routers.patient_files.run_deidentification", lambda **kw: None)

    patient_id = _patient(as_admin)
    record = _upload(as_admin, patient_id).json()[0]

    response = as_admin.post(f"/files/{record['id']}/deidentify")
    assert response.status_code == 200
    assert response.json()["deid_status"] == "processing"


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
    # patients:read covers reading documents...
    assert client.get(f"/patients/{patient_id}/files").status_code == 200
    assert client.get(f"/files/{record['id']}").status_code == 200
    # ...but changing them needs patients:update.
    assert _upload(client, patient_id).status_code == 403
    assert client.delete(f"/files/{record['id']}").status_code == 403
    assert client.post(f"/files/{record['id']}/deidentify").status_code == 403
