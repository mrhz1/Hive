"""The de-identified file library and its own files:* permission."""
import pathlib

import pytest

from app import storage
from conftest import ADMIN_USER, NOBODY_USER, VIEWER_USER, minimal_patient


@pytest.fixture
def deid_dirs(tmp_path, monkeypatch):
    pdf = tmp_path / "final" / "pdf"
    dicom = tmp_path / "final" / "dicom"
    word = tmp_path / "final" / "word"
    monkeypatch.setattr(storage, "DEID_PDF_DIR", pdf)
    monkeypatch.setattr(storage, "DEID_DICOM_DIR", dicom)
    monkeypatch.setattr(storage, "DEID_WORD_DIR", word)
    monkeypatch.setattr(
        storage,
        "DEID_DIRS",
        {"pdf": pdf, "dcm": dicom, "dicom": dicom, "doc": word, "docx": word},
    )
    return {"pdf": pdf, "dicom": dicom, "word": word}


def _patient_with_file(client, storage_root, name="scan.pdf", redacted=True):
    patient_id = client.post("/patients", json=minimal_patient()).json()["id"]
    application_id = client.post(
        "/applications", json={"patient_id": patient_id}
    ).json()["id"]
    record = client.post(
        f"/applications/{application_id}/files",
        files=[("files", (name, b"%PDF-1.4 fake", "application/pdf"))],
    ).json()[0]

    if redacted:
        original = pathlib.Path(record["file_path"])
        output = original.parent / f"{original.stem}_deid.pdf"
        output.write_bytes(b"%PDF-1.4 redacted")
        client.put(
            f"/files/{record['id']}",
            json={
                "deid_status": "done",
                "is_deidentified": True,
                "deidentified_file_name": output.name,
                "de_identified_file_path": str(output),
            },
        )
    return patient_id, record


# ------------------------------------------------------------- browsing

def test_only_files_with_a_redacted_copy_are_listed(as_admin, storage_root):
    _patient_with_file(as_admin, storage_root, name="done.pdf", redacted=True)
    _patient_with_file(as_admin, storage_root, name="raw.pdf", redacted=False)

    rows = as_admin.get("/files-library").json()

    assert len(rows) == 1
    assert rows[0]["original_file_name"] == "done.pdf"


def test_rows_carry_the_columns_the_table_shows(as_admin, storage_root):
    """name, type, date -- plus the patient id every row is filed under."""
    patient_id, _ = _patient_with_file(as_admin, storage_root)

    row = as_admin.get("/files-library").json()[0]

    assert row["patient_id"] == patient_id
    assert row["file_type"] == "pdf"
    assert row["name"].endswith("_deid.pdf")
    assert row["created_at"]


def test_listing_can_be_scoped_to_one_patient(as_admin, storage_root):
    first, _ = _patient_with_file(as_admin, storage_root)
    _patient_with_file(as_admin, storage_root)

    rows = as_admin.get("/files-library", params={"patient_id": first}).json()

    assert [r["patient_id"] for r in rows] == [first]


def test_downloading_serves_the_redacted_bytes_not_the_original(
    as_admin, storage_root
):
    _patient_with_file(as_admin, storage_root)
    file_id = as_admin.get("/files-library").json()[0]["id"]

    response = as_admin.get(f"/files-library/{file_id}/content")

    assert response.status_code == 200
    assert response.content == b"%PDF-1.4 redacted"


# ---------------------------------------------------------- permissions

def test_reading_requires_files_read(client, storage_root):
    client.headers.update({"REMOTE-USER": NOBODY_USER})

    response = client.get("/files-library")

    assert response.status_code == 403
    assert "files:read" in response.json()["error"]["detail"]


def test_a_read_only_role_can_browse_but_not_take_copies_away(
    as_admin, client, storage_root
):
    """The point of a separate files:download."""
    _, record = _patient_with_file(as_admin, storage_root)

    client.headers.update({"REMOTE-USER": VIEWER_USER})

    assert client.get("/files-library").status_code == 200

    denied = client.get(f"/files-library/{record['id']}/content")
    assert denied.status_code == 403
    assert "files:download" in denied.json()["error"]["detail"]


def test_a_read_only_role_cannot_upload_or_delete(as_admin, client, storage_root):
    _, record = _patient_with_file(as_admin, storage_root)
    client.headers.update({"REMOTE-USER": VIEWER_USER})

    assert client.delete(f"/files-library/{record['id']}").status_code == 403


def test_every_files_action_exists(client):
    from app import security

    for action in ("read", "upload", "download", "delete"):
        assert f"files:{action}" in security.KNOWN_PERMISSIONS


def test_files_actions_do_not_leak_into_other_models():
    """A per-model action map, so nobody gets offered 'user:download'."""
    from app import security

    assert "user:download" not in security.KNOWN_PERMISSIONS
    assert "role:upload" not in security.KNOWN_PERMISSIONS
    assert "files:view" not in security.KNOWN_PERMISSIONS


# -------------------------------------------------------------- uploads

def test_uploading_a_new_manually_redacted_file(as_admin, storage_root, deid_dirs):
    patient_id, _ = _patient_with_file(as_admin, storage_root)

    response = as_admin.post(
        "/files-library",
        data={"patient_id": patient_id},
        files=[("file", ("manual.pdf", b"%PDF-1.4 hand redacted", "application/pdf"))],
    )

    assert response.status_code == 201, response.text
    row = response.json()
    assert row["patient_id"] == patient_id
    assert row["deid_status"] == "done"
    assert (deid_dirs["pdf"] / row["name"]).read_bytes() == b"%PDF-1.4 hand redacted"


def test_replacing_keeps_the_same_id_and_stays_done(
    as_admin, storage_root, deid_dirs
):
    """The stated case: the pipeline missed an identifier, a human redacted it properly, and the corrected file goes in over the top."""
    patient_id, record = _patient_with_file(as_admin, storage_root)
    before = as_admin.get("/files-library").json()[0]

    response = as_admin.post(
        "/files-library",
        data={"patient_id": patient_id, "replaces_file_id": record["id"]},
        files=[("file", ("fixed.pdf", b"%PDF-1.4 properly redacted", "application/pdf"))],
    )

    assert response.status_code == 201, response.text
    after = response.json()

    assert after["id"] == before["id"], "the id changed"
    assert after["deid_status"] == "done"

    rows = as_admin.get("/files-library").json()
    assert len(rows) == 1, "replacing created a second row"

    content = as_admin.get(f"/files-library/{after['id']}/content").content
    assert content == b"%PDF-1.4 properly redacted"


def test_replacing_across_patients_is_refused(as_admin, storage_root, deid_dirs):
    """Otherwise one patient's document is attached to another's record."""
    _, record = _patient_with_file(as_admin, storage_root)
    other_patient = as_admin.post(
        "/patients", json=minimal_patient(ptemail="other@example.com")
    ).json()["id"]

    response = as_admin.post(
        "/files-library",
        data={"patient_id": other_patient, "replaces_file_id": record["id"]},
        files=[("file", ("x.pdf", b"data", "application/pdf"))],
    )

    assert response.status_code == 422
    assert "different patient" in response.json()["error"]["detail"]


def test_upload_rejects_a_format_the_library_does_not_handle(
    as_admin, storage_root, deid_dirs
):
    patient_id, _ = _patient_with_file(as_admin, storage_root)

    response = as_admin.post(
        "/files-library",
        data={"patient_id": patient_id},
        files=[("file", ("notes.txt", b"data", "text/plain"))],
    )

    assert response.status_code == 422


def test_upload_records_the_metadata_facts(as_admin, storage_root, deid_dirs):
    patient_id, record = _patient_with_file(as_admin, storage_root)

    as_admin.post(
        "/files-library",
        data={"patient_id": patient_id, "replaces_file_id": record["id"]},
        files=[("file", ("fixed.pdf", b"data", "application/pdf"))],
    )

    metadata = as_admin.get(f"/files/{record['id']}/metadata").json()["metadata"]
    assert metadata["patient_id"] == patient_id
    assert metadata["deidentified_by"] == "manual upload"
    assert metadata["deidentified_file_type"] == "pdf"


# -------------------------------------------------------------- deleting

def test_deleting_removes_the_redacted_copy_but_keeps_the_original(
    as_admin, storage_root
):
    _, record = _patient_with_file(as_admin, storage_root)
    original = pathlib.Path(record["file_path"])
    redacted = pathlib.Path(
        as_admin.get(f"/files/{record['id']}").json()["de_identified_file_path"]
    )

    assert as_admin.delete(f"/files-library/{record['id']}").status_code == 204

    assert not redacted.exists(), "the redacted copy is still on disk"
    assert original.is_file(), "the original was deleted -- it is the record of receipt"

    after = as_admin.get(f"/files/{record['id']}").json()
    assert after["deid_status"] == "pending"
    assert after["de_identified_file_path"] is None
    assert as_admin.get("/files-library").json() == []
