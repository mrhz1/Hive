"""Application document endpoints."""
import io
import pathlib
import re

import pytest
from conftest import ADMIN_USER, VIEWER_USER, minimal_patient

# <patient id>-<time received>
FOLDER = re.compile(r"^[A-Z0-9]{6}-\d{8}T\d{6}Z$")
# <patient id>-<document type>-<16-digit serial>.<ext>
DOCUMENT = re.compile(r"^[A-Z0-9]{6}-[a-z0-9]+-\d{16}\.[a-z0-9]+$")


def _application(client):
    """A patient and an application for them -- files hang off the latter."""
    return _patient_and_application(client)[1]


def _patient_and_application(client, **patient_overrides):
    """Both ids, for the tests that care where a document lands on disk."""
    patient_id = client.post(
        "/patients", json=minimal_patient(**patient_overrides)
    ).json()["id"]
    application_id = client.post(
        "/applications", json={"patient_id": patient_id}
    ).json()["id"]
    return patient_id, application_id


def _upload(client, application_id, name="scan.pdf", data=b"%PDF-1.4 fake", **kwargs):
    return client.post(
        f"/applications/{application_id}/files",
        files=[("files", (name, data, "application/pdf"))],
        **kwargs,
    )


def test_upload_lands_under_the_patient(as_admin, storage_root):
    patient_id, application_id = _patient_and_application(as_admin)

    response = _upload(as_admin, application_id)
    assert response.status_code == 201, response.text

    record = response.json()[0]
    assert record["application_id"] == application_id
    assert record["original_file_name"] == "scan.pdf"
    assert record["file_extension"] == "pdf"
    assert record["file_size"] == len(b"%PDF-1.4 fake")

    # Fresh uploads are not de-identified, and must not claim to be.
    assert record["deid_status"] == "pending"
    assert record["is_deidentified"] is False
    assert record["de_identified_file_path"] is None

    stored = pathlib.Path(record["file_path"])
    assert stored.is_file()
    assert FOLDER.match(stored.parent.name), stored.parent.name
    assert stored.parent.name.startswith(f"{patient_id}-")
    assert DOCUMENT.match(stored.name), stored.name
    assert stored.name.startswith(f"{patient_id}-pdf-")


def test_document_type_comes_from_the_format(as_admin, storage_root):
    patient_id, application_id = _patient_and_application(as_admin)

    for name, expected in (
        ("scan.pdf", "pdf"),
        ("study.dcm", "dicom"),
        ("letter.docx", "word"),
        ("notes.txt", "txt"),
    ):
        record = _upload(as_admin, application_id, name=name).json()[0]
        stored = pathlib.Path(record["file_path"])
        assert stored.name.startswith(f"{patient_id}-{expected}-"), stored.name


def test_serials_do_not_repeat_across_a_batch(as_admin, storage_root):
    _, application_id = _patient_and_application(as_admin)

    response = as_admin.post(
        f"/applications/{application_id}/files",
        files=[
            ("files", (f"scan{n}.pdf", b"%PDF-1.4 fake", "application/pdf"))
            for n in range(12)
        ],
    )

    names = [pathlib.Path(r["file_path"]).name for r in response.json()]
    assert len(set(names)) == 12, names


def test_one_batch_shares_one_folder(as_admin, storage_root):
    _, application_id = _patient_and_application(as_admin)

    response = as_admin.post(
        f"/applications/{application_id}/files",
        files=[
            ("files", (f"scan{n}.pdf", b"%PDF-1.4 fake", "application/pdf"))
            for n in range(5)
        ],
    )

    folders = {pathlib.Path(r["file_path"]).parent for r in response.json()}
    assert len(folders) == 1, "one upload must not be split across folders"


def test_upload_name_never_reaches_the_filesystem(as_admin, storage_root):
    """An upload name is arbitrary and often identifying in itself, so the stored path is built entirely from ids."""
    _, application_id = _patient_and_application(as_admin)

    record = _upload(as_admin, application_id, name="Jane Doe referral.pdf").json()[0]

    stored = pathlib.Path(record["file_path"])
    assert "jane" not in str(stored).lower()
    assert "referral" not in str(stored).lower()
    assert record["original_file_name"] == "Jane Doe referral.pdf"


def test_the_file_row_matches_the_cloudera_columns(as_admin, storage_root):
    """Including the two spellings the metastore actually has: `deidentified_file_name` against `de_identified_file_path`."""
    application_id = _application(as_admin)
    record = _upload(as_admin, application_id).json()[0]

    assert set(record) == {
        "id", "application_id", "original_file_name", "sanitized_file_name",
        "deidentified_file_name", "file_extension", "mime_type", "file_size",
        "deid_status", "is_deidentified", "created_at", "description",
        "file_path", "de_identified_file_path",
        "review_status", "review_note",
    }


def test_a_folder_upload_sanitises_paths(as_admin, storage_root):
    """webkitRelativePath sends 'sub/dir/x.pdf'; '../' must never be honoured against the storage root."""
    application_id = _application(as_admin)

    response = as_admin.post(
        f"/applications/{application_id}/files",
        files=[("files", ("../../etc/passwd.pdf", b"data", "application/pdf"))],
    )
    record = response.json()[0]

    assert record["original_file_name"] == "../../etc/passwd.pdf"

    stored = pathlib.Path(record["file_path"])
    assert DOCUMENT.match(stored.name), stored.name
    assert stored.is_file()
    assert storage_root.resolve() in stored.resolve().parents


def test_listing_is_scoped_to_one_application(as_admin, storage_root):
    first = _application(as_admin)
    second = _application(as_admin)

    _upload(as_admin, first, name="a.pdf")
    _upload(as_admin, second, name="b.pdf")

    def names(application_id):
        return [
            f["original_file_name"]
            for f in as_admin.get(f"/applications/{application_id}/files").json()
        ]

    assert names(first) == ["a.pdf"]
    assert names(second) == ["b.pdf"]


def test_files_for_an_unknown_application_are_a_404(as_admin):
    """404 rather than an empty list, so a wrong id is distinguishable from an application with no documents."""
    assert as_admin.get("/applications/nope/files").status_code == 404
    assert _upload(as_admin, "nope").status_code == 404


def test_downloading_serves_the_stored_bytes(as_admin, storage_root):
    application_id = _application(as_admin)
    record = _upload(as_admin, application_id, data=b"%PDF-1.4 hello").json()[0]

    response = as_admin.get(f"/files/{record['id']}/content")
    assert response.status_code == 200
    assert response.content == b"%PDF-1.4 hello"


def test_asking_for_a_redacted_copy_that_does_not_exist(as_admin, storage_root):
    application_id = _application(as_admin)
    record = _upload(as_admin, application_id).json()[0]

    response = as_admin.get(
        f"/files/{record['id']}/content", params={"deidentified": True}
    )
    assert response.status_code == 422
    assert "not been de-identified" in response.json()["error"]["detail"]


def test_deleting_an_application_removes_its_documents(as_admin, storage_root):
    application_id = _application(as_admin)
    record = _upload(as_admin, application_id).json()[0]
    on_disk = pathlib.Path(record["file_path"])
    assert on_disk.is_file()

    assert (
        as_admin.delete(
            f"/applications/{application_id}", params={"reason": "no longer needed"}
        ).status_code
        == 204
    )

    assert as_admin.get(f"/files/{record['id']}").status_code == 404
    assert not on_disk.exists()


def test_deleting_a_patient_removes_documents_two_levels_down(as_admin, storage_root):
    """patient -> applications -> files."""
    patient_id = as_admin.post("/patients", json=minimal_patient()).json()["id"]
    application_id = as_admin.post(
        "/applications", json={"patient_id": patient_id}
    ).json()["id"]
    record = _upload(as_admin, application_id).json()[0]
    on_disk = pathlib.Path(record["file_path"])

    assert as_admin.delete(f"/patients/{patient_id}").status_code == 204

    assert as_admin.get(f"/files/{record['id']}").status_code == 404
    assert as_admin.get(f"/applications/{application_id}").status_code == 404
    assert not on_disk.exists()


def test_deleting_one_file_removes_its_bytes(as_admin, storage_root):
    application_id = _application(as_admin)
    record = _upload(as_admin, application_id).json()[0]
    on_disk = storage_root / application_id / f"{record['id']}_scan.pdf"

    assert as_admin.delete(f"/files/{record['id']}").status_code == 204
    assert not on_disk.exists()
    assert as_admin.get(f"/applications/{application_id}/files").json() == []


def test_deleting_a_file_removes_its_metadata_row(as_admin, storage_root, store):
    application_id = _application(as_admin)
    record = _upload(as_admin, application_id).json()[0]
    assert store["file_metadata"]

    as_admin.delete(f"/files/{record['id']}")
    assert store["file_metadata"] == []


# ------------------------------------------------------ de-identification

def test_deidentify_rejects_an_unsupported_format(as_admin, storage_root):
    application_id = _application(as_admin)
    record = as_admin.post(
        f"/applications/{application_id}/files",
        files=[("files", ("notes.txt", b"plain text", "text/plain"))],
    ).json()[0]

    response = as_admin.post(f"/files/{record['id']}/deidentify")
    assert response.status_code == 422
    assert "cannot be de-identified" in response.json()["error"]["detail"]


@pytest.mark.parametrize(
    "name,mime",
    [
        ("scan.pdf", "application/pdf"),
        ("study.dcm", "application/dicom"),
        ("letter.docx",
         "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ("legacy.doc", "application/msword"),
    ],
)
def test_deidentify_accepts_every_supported_format(
    as_admin, storage_root, monkeypatch, name, mime
):
    """PDF was the only format for a long time; DICOM and Word have to be accepted at the API boundary too, or the pipeline never sees them."""
    monkeypatch.setattr("app.deid.dispatch_deidentification", lambda **kwargs: None)
    application_id = _application(as_admin)
    record = as_admin.post(
        f"/applications/{application_id}/files",
        files=[("files", (name, b"bytes", mime))],
    ).json()[0]

    response = as_admin.post(f"/files/{record['id']}/deidentify")

    assert response.status_code == 200, response.text


def test_deidentify_marks_the_row_processing(as_admin, storage_root, monkeypatch):
    """The row is marked before the job starts, so the UI reflects it on the very next read."""
    monkeypatch.setattr(
        "app.routers.patient_application_files.dispatch_deidentification",
        lambda **kw: None,
    )

    application_id = _application(as_admin)
    record = _upload(as_admin, application_id).json()[0]

    response = as_admin.post(f"/files/{record['id']}/deidentify")
    assert response.status_code == 200
    assert response.json()["deid_status"] == "processing"


def test_deidentify_marks_the_row_queued_on_the_job_backend(
    as_admin, storage_root, monkeypatch
):
    """Under DEID_BACKEND=cml_job nothing is processing yet -- a Job run has only been asked for."""
    monkeypatch.setattr(
        "app.routers.patient_application_files.dispatch_deidentification",
        lambda **kw: None,
    )
    monkeypatch.setattr("app.deid.DEID_BACKEND", "cml_job")

    application_id = _application(as_admin)
    record = _upload(as_admin, application_id).json()[0]

    response = as_admin.post(f"/files/{record['id']}/deidentify")
    assert response.status_code == 200
    assert response.json()["deid_status"] == "queued"


def test_deidentify_rejects_a_file_already_in_flight(
    as_admin, storage_root, monkeypatch
):
    """A second click must not start a second run."""
    monkeypatch.setattr(
        "app.routers.patient_application_files.dispatch_deidentification",
        lambda **kw: None,
    )

    application_id = _application(as_admin)
    record = _upload(as_admin, application_id).json()[0]
    assert record["deid_status"] == "pending"

    assert as_admin.post(f"/files/{record['id']}/deidentify").status_code == 200

    second = as_admin.post(f"/files/{record['id']}/deidentify")
    assert second.status_code == 422
    assert "already queued" in second.json()["error"]["detail"]


# -------------------------------------------------------------- metadata

def _pdf_with_metadata() -> bytes:
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_metadata({"/Title": "Discharge Summary", "/Author": "Dr Who"})
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _docx_with_metadata() -> bytes:
    import docx

    document = docx.Document()
    document.core_properties.title = "Referral Letter"
    document.core_properties.author = "Dr Who"
    document.add_paragraph("Hello")
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _dicom_with_metadata() -> bytes:
    import pydicom
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian

    dataset = Dataset()
    dataset.PatientName = "Doe^Jane"
    dataset.PatientID = "MRN-1234"
    dataset.Modality = "CT"
    dataset.StudyDescription = "Chest"

    dataset.file_meta = FileMetaDataset()
    dataset.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    dataset.file_meta.MediaStorageSOPClassUID = pydicom.uid.CTImageStorage
    dataset.file_meta.MediaStorageSOPInstanceUID = pydicom.uid.generate_uid()

    buffer = io.BytesIO()
    dataset.save_as(buffer, enforce_file_format=True)
    return buffer.getvalue()


def test_pdf_metadata_is_extracted_on_upload(as_admin, storage_root):
    application_id = _application(as_admin)
    record = _upload(as_admin, application_id, data=_pdf_with_metadata()).json()[0]

    response = as_admin.get(f"/files/{record['id']}/metadata")
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["file_type"] == "pdf"
    assert body["status"] == "ok"
    assert body["metadata"]["title"] == "Discharge Summary"
    assert body["metadata"]["author"] == "Dr Who"
    assert body["metadata"]["page_count"] == "1"


def test_word_metadata_is_extracted_on_upload(as_admin, storage_root):
    application_id = _application(as_admin)
    record = as_admin.post(
        f"/applications/{application_id}/files",
        files=[
            (
                "files",
                (
                    "referral.docx",
                    _docx_with_metadata(),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ),
            )
        ],
    ).json()[0]

    body = as_admin.get(f"/files/{record['id']}/metadata").json()
    assert body["file_type"] == "word"
    assert body["status"] == "ok"
    assert body["metadata"]["title"] == "Referral Letter"
    assert body["metadata"]["author"] == "Dr Who"


def test_dicom_metadata_is_extracted_on_upload(as_admin, storage_root):
    application_id = _application(as_admin)
    record = as_admin.post(
        f"/applications/{application_id}/files",
        files=[("files", ("scan.dcm", _dicom_with_metadata(), "application/dicom"))],
    ).json()[0]

    body = as_admin.get(f"/files/{record['id']}/metadata").json()
    assert body["file_type"] == "dicom"
    assert body["status"] == "ok"
    assert body["metadata"]["PatientName"] == "Doe^Jane"
    assert body["metadata"]["Modality"] == "CT"


def test_an_unreadable_document_records_why_rather_than_failing_the_upload(
    as_admin, storage_root
):
    """The bytes are already on disk by the time extraction runs -- a malformed PDF is a missing panel, not a lost document."""
    application_id = _application(as_admin)
    response = _upload(as_admin, application_id, data=b"not really a pdf")

    assert response.status_code == 201
    body = as_admin.get(f"/files/{response.json()[0]['id']}/metadata").json()
    assert body["status"] == "failed"
    assert body["error"]
    assert body["metadata"] == {}


def test_a_format_we_do_not_read_is_recorded_unsupported(as_admin, storage_root):
    """A row still exists, so the UI can tell "nothing to show" apart from "never looked"."""
    application_id = _application(as_admin)
    record = as_admin.post(
        f"/applications/{application_id}/files",
        files=[("files", ("notes.txt", b"plain text", "text/plain"))],
    ).json()[0]

    body = as_admin.get(f"/files/{record['id']}/metadata").json()
    assert body["status"] == "unsupported"
    assert body["metadata"] == {}


def test_metadata_is_stored_as_a_json_string(as_admin, storage_root, store):
    """ORC has no JSON type -- the column is a STRING, the same convention audit_logs uses."""
    import json

    application_id = _application(as_admin)
    _upload(as_admin, application_id, data=_pdf_with_metadata())

    raw = store["file_metadata"][0]["metadata"]
    assert isinstance(raw, str)
    assert json.loads(raw)["title"] == "Discharge Summary"


def test_metadata_for_an_unknown_file_is_a_404(as_admin):
    assert as_admin.get("/files/nope/metadata").status_code == 404


# ----------------------------------------------------------- permissions

def test_empty_uploads_are_skipped_not_fatal(as_admin, storage_root):
    """Picking a folder can yield directory entries and hidden files."""
    application_id = _application(as_admin)

    response = as_admin.post(
        f"/applications/{application_id}/files",
        files=[
            ("files", ("empty", b"", "application/octet-stream")),
            ("files", ("real.pdf", b"%PDF-1.4", "application/pdf")),
        ],
    )
    assert response.status_code == 201
    assert [f["original_file_name"] for f in response.json()] == ["real.pdf"]


def test_file_access_uses_the_application_permissions(client, storage_root):
    """These documents are part of a submission, so anyone who may read an application may read them -- and changing them is application:update."""
    admin = {"REMOTE-USER": ADMIN_USER}
    patient_id = client.post(
        "/patients", json=minimal_patient(), headers=admin
    ).json()["id"]
    application_id = client.post(
        "/applications", json={"patient_id": patient_id}, headers=admin
    ).json()["id"]
    record = _upload(client, application_id, headers=admin).json()[0]

    client.headers.update({"REMOTE-USER": VIEWER_USER})
    # application:view covers reading documents and their metadata...
    assert client.get(f"/applications/{application_id}/files").status_code == 200
    assert client.get(f"/files/{record['id']}").status_code == 200
    assert client.get(f"/files/{record['id']}/metadata").status_code == 200
    # ...but changing them needs application:update.
    assert _upload(client, application_id).status_code == 403
    assert client.delete(f"/files/{record['id']}").status_code == 403
    assert client.post(f"/files/{record['id']}/deidentify").status_code == 403




def test_a_file_starts_undecided(as_admin, storage_root):
    application_id = _application(as_admin)
    record = _upload(as_admin, application_id).json()[0]

    assert record["review_status"] == "pending"
    assert record["review_note"] is None


def test_approving_a_file(as_admin, storage_root):
    application_id = _application(as_admin)
    record = _upload(as_admin, application_id).json()[0]

    response = as_admin.post(
        f"/files/{record['id']}/review", json={"review_status": "approved"}
    )

    assert response.status_code == 200
    assert response.json()["review_status"] == "approved"


def test_rejecting_a_file_keeps_the_reason(as_admin, storage_root):
    application_id = _application(as_admin)
    record = _upload(as_admin, application_id).json()[0]

    response = as_admin.post(
        f"/files/{record['id']}/review",
        json={"review_status": "rejected", "review_note": "illegible, rescan"},
    )

    assert response.status_code == 200
    assert response.json()["review_status"] == "rejected"
    assert response.json()["review_note"] == "illegible, rescan"


def test_rejecting_without_a_reason_is_refused(as_admin, storage_root):
    """'Rejected' with no reason gives whoever has to fix it nothing."""
    application_id = _application(as_admin)
    record = _upload(as_admin, application_id).json()[0]

    for payload in (
        {"review_status": "rejected"},
        {"review_status": "rejected", "review_note": "   "},
    ):
        response = as_admin.post(f"/files/{record['id']}/review", json=payload)
        assert response.status_code == 422, payload
        assert "reason is required" in response.json()["error"]["detail"]


def test_approving_clears_an_earlier_rejection_reason(as_admin, storage_root):
    application_id = _application(as_admin)
    record = _upload(as_admin, application_id).json()[0]

    as_admin.post(
        f"/files/{record['id']}/review",
        json={"review_status": "rejected", "review_note": "wrong patient"},
    )
    approved = as_admin.post(
        f"/files/{record['id']}/review", json={"review_status": "approved"}
    ).json()

    assert approved["review_status"] == "approved"
    assert approved["review_note"] is None, "a stale rejection reason survived"


def test_review_needs_application_update(client, storage_root):
    admin = {"REMOTE-USER": ADMIN_USER}
    patient_id = client.post(
        "/patients", json=minimal_patient(), headers=admin
    ).json()["id"]
    application_id = client.post(
        "/applications", json={"patient_id": patient_id}, headers=admin
    ).json()["id"]
    record = _upload(client, application_id, headers=admin).json()[0]

    client.headers.update({"REMOTE-USER": VIEWER_USER})
    response = client.post(
        f"/files/{record['id']}/review", json={"review_status": "approved"}
    )

    assert response.status_code == 403
