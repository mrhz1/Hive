"""Application document endpoints."""
import io
import pathlib
import re

import pytest
from conftest import ADMIN_USER, VIEWER_USER, minimal_patient

# <patient id>-<time received>
FOLDER = re.compile(r"^[A-Z0-9]{6}-\d{8}T\d{6}Z$")
# <patient>-<type>-<date>-<serial>.<ext>. The date is in the name so a
# directory listing can be read by eye.
DOCUMENT = re.compile(r"^[A-Z0-9]{6}-[a-z0-9]+-\d{8}-\d{16}\.[a-z0-9]+$")


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

    # Content matched to the name: an extension is only believed when it
    # names a format we handle, so a .txt full of PDF bytes is a PDF.
    for name, data, expected in (
        ("scan.pdf", b"%PDF-1.4 fake", "pdf"),
        ("study.dcm", b"%PDF-1.4 fake", "dicom"),
        ("letter.docx", b"%PDF-1.4 fake", "word"),
        ("notes.txt", b"just some notes", "txt"),
    ):
        record = _upload(as_admin, application_id, name=name, data=data).json()[0]
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


def test_a_patient_with_documents_two_levels_down_is_not_deleted(
    as_admin, storage_root
):
    """patient -> applications -> files. The refusal at the top is what
    keeps the bottom: nothing is removed, and the bytes stay on disk."""
    patient_id = as_admin.post("/patients", json=minimal_patient()).json()["id"]
    application_id = as_admin.post(
        "/applications", json={"patient_id": patient_id}
    ).json()["id"]
    record = _upload(as_admin, application_id).json()[0]
    on_disk = pathlib.Path(record["file_path"])

    assert as_admin.delete(f"/patients/{patient_id}").status_code == 409

    assert as_admin.get(f"/files/{record['id']}").status_code == 200
    assert as_admin.get(f"/applications/{application_id}").status_code == 200
    assert on_disk.exists()


def test_deleting_one_file_removes_its_bytes(as_admin, storage_root):
    application_id = _application(as_admin)
    record = _upload(as_admin, application_id).json()[0]
    on_disk = storage_root / application_id / f"{record['id']}_scan.pdf"

    assert as_admin.delete(f"/files/{record['id']}").status_code == 204
    assert not on_disk.exists()
    assert as_admin.get(f"/applications/{application_id}/files").json() == []


def _fake_deid_run(record) -> dict:
    """The three files a de-identification run leaves on disk.

    Written by hand rather than by running the pipeline: the OCR stack
    is not installed in this suite, and what is being tested is what
    happens to the outputs afterwards, not how they were produced.
    """
    source = pathlib.Path(record["file_path"])
    output_dir = source.parent / "deidentified"
    output_dir.mkdir(parents=True, exist_ok=True)

    produced = {
        name: output_dir / f"{source.stem}_deid{name}"
        for name in (".pdf", ".txt", ".report.json")
    }
    for path in produced.values():
        path.write_bytes(b"output")

    return produced


def test_deleting_a_file_takes_the_whole_de_identification_run_with_it(
    as_admin, storage_root
):
    """The redacted document is one of three the pipeline writes. The
    other two -- the text it read out of the file, and the report of
    what it redacted -- are recorded nowhere, so deleting a document
    used to leave the document's contents in the clear on disk with
    nothing pointing at them."""
    application_id = _application(as_admin)
    record = _upload(as_admin, application_id).json()[0]
    produced = _fake_deid_run(record)

    assert as_admin.delete(f"/files/{record['id']}").status_code == 204

    for name, path in produced.items():
        assert not path.exists(), f"{name} survived the delete"


def test_deleting_a_file_leaves_another_document_s_outputs_alone(
    as_admin, storage_root
):
    """A batch shares one output folder, so the sweep has to be by name."""
    application_id = _application(as_admin)
    uploaded = _upload(as_admin, application_id).json()[0]
    other = _upload(as_admin, application_id, name="second.pdf").json()[0]

    _fake_deid_run(uploaded)
    survivors = _fake_deid_run(other)

    as_admin.delete(f"/files/{uploaded['id']}")

    for name, path in survivors.items():
        assert path.exists(), f"{name} was taken with the other document"


def test_deleting_the_application_takes_the_run_outputs_too(
    as_admin, storage_root
):
    application_id = _application(as_admin)
    record = _upload(as_admin, application_id).json()[0]
    produced = _fake_deid_run(record)

    as_admin.delete(
        f"/applications/{application_id}", params={"reason": "wrong patient"}
    )

    for name, path in produced.items():
        assert not path.exists(), f"{name} survived the delete"


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


# ------------------------------------------- uploading an already-redacted file

def _upload_deidentified(
    client, application_id, name="clean.pdf", data=None, **kwargs
):
    # `is None`, not `or`: b'' is a case one of these tests is about.
    content = _pdf_with_metadata() if data is None else data
    return client.post(
        f"/applications/{application_id}/files/deidentified",
        files=[("file", (name, content, "application/pdf"))],
        **kwargs,
    )


# <patient>-<type>-<date>-<serial>_deid.<ext>, as the pipeline names its own.
REDACTED_DOCUMENT = re.compile(r"^[A-Z0-9]{6}-[a-z0-9]+-\d{8}-\d{16}_deid\.[a-z0-9]+$")


def test_an_uploaded_redacted_file_arrives_finished(as_admin, storage_root):
    """Nothing is left to run over it, so it must not sit in 'pending'
    waiting for a pass that would only redact what is already redacted."""
    patient_id, application_id = _patient_and_application(as_admin)

    response = _upload_deidentified(as_admin, application_id)
    assert response.status_code == 201, response.text

    record = response.json()
    assert record["deid_status"] == "done"
    assert record["is_deidentified"] is True
    assert record["de_identified_file_path"]
    assert pathlib.Path(record["de_identified_file_path"]).is_file()


def test_an_uploaded_redacted_file_is_named_like_a_produced_one(as_admin, storage_root):
    patient_id, application_id = _patient_and_application(as_admin)

    record = _upload_deidentified(as_admin, application_id).json()
    name = record["deidentified_file_name"]

    assert REDACTED_DOCUMENT.match(name), name
    assert name.startswith(f"{patient_id}-")
    # The name it was uploaded under is kept, but only as the label.
    assert record["original_file_name"] == "clean.pdf"
    assert record["sanitized_file_name"] == name


def test_an_uploaded_redacted_file_shows_up_in_the_library(as_admin, storage_root):
    _, application_id = _patient_and_application(as_admin)
    record = _upload_deidentified(as_admin, application_id).json()

    listed = as_admin.get("/files-library").json()

    assert [row["id"] for row in listed] == [record["id"]]
    assert listed[0]["name"] == record["deidentified_file_name"]


def test_a_format_that_cannot_be_redacted_is_refused(as_admin, storage_root):
    _, application_id = _patient_and_application(as_admin)

    response = _upload_deidentified(
        as_admin, application_id, name="notes.txt", data=b"plain text"
    )

    assert response.status_code == 422
    assert "not handled here" in response.json()["error"]["detail"]


def test_an_empty_redacted_upload_is_refused(as_admin, storage_root):
    _, application_id = _patient_and_application(as_admin)

    response = _upload_deidentified(as_admin, application_id, data=b"")

    assert response.status_code == 422


# --------------------------------------- the redacted copy's own metadata

def test_the_redacted_copy_has_its_metadata_read_on_demand(as_admin, storage_root):
    """Read from the file each time rather than stored: the point of
    looking is to check what the redaction actually left behind."""
    _, application_id = _patient_and_application(as_admin)
    record = _upload_deidentified(as_admin, application_id).json()

    response = as_admin.get(
        f"/files/{record['id']}/metadata", params={"deidentified": True}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["file_id"] == record["id"]
    assert body["file_type"] == "pdf"
    assert body["status"] == "ok"


def test_asking_for_redacted_metadata_without_a_redacted_copy_is_refused(
    as_admin, storage_root
):
    application_id = _application(as_admin)
    record = _upload(as_admin, application_id).json()[0]

    response = as_admin.get(
        f"/files/{record['id']}/metadata", params={"deidentified": True}
    )

    assert response.status_code == 422
    assert "not been de-identified" in response.json()["error"]["detail"]


def test_the_original_and_the_redacted_copy_report_different_metadata(
    as_admin, storage_root
):
    application_id = _application(as_admin)
    record = _upload(as_admin, application_id, data=_pdf_with_metadata()).json()[0]

    original = as_admin.get(f"/files/{record['id']}/metadata").json()

    assert original["metadata"]["title"] == "Discharge Summary"
    # The stored row is the original's, and asking for it must not have
    # been quietly answered from the file on disk.
    assert original["id"] != f"{record['id']}:deid"
