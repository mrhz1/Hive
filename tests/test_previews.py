"""Rendering DICOM and Word so a browser shows them instead of downloading.

An <iframe> renders a PDF on its own; for the other two formats there is
nothing browser-native to point it at, so the API produces something
there is -- a PNG frame, and text.
"""
import io
import pathlib

import pytest
from conftest import minimal_patient

pytestmark = pytest.mark.usefixtures("storage_root")


def _application(client):
    patient_id = client.post("/patients", json=minimal_patient()).json()["id"]
    return client.post(
        "/applications", json={"patient_id": patient_id}
    ).json()["id"]


def _dicom_bytes(frames=1, rows=32, columns=48, photometric="MONOCHROME2"):
    """A small uncompressed study, built the way a modality would."""
    numpy = pytest.importorskip("numpy")
    pytest.importorskip("pydicom")
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian

    dataset = Dataset()
    dataset.PatientName = "Doe^Jane"
    dataset.PatientID = "MRN4471"
    dataset.Modality = "CR"
    dataset.Rows, dataset.Columns = rows, columns
    dataset.SamplesPerPixel = 1
    dataset.PhotometricInterpretation = photometric
    dataset.BitsAllocated = 8
    dataset.BitsStored = 8
    dataset.HighBit = 7
    dataset.PixelRepresentation = 0
    if frames > 1:
        dataset.NumberOfFrames = frames

    gradient = numpy.tile(
        numpy.linspace(0, 255, columns, dtype=numpy.uint8), (rows, 1)
    )
    stack = numpy.stack([gradient] * frames) if frames > 1 else gradient
    dataset.PixelData = stack.tobytes()

    dataset.file_meta = FileMetaDataset()
    dataset.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    dataset.file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.1"
    dataset.file_meta.MediaStorageSOPInstanceUID = "1.2.3.4"

    buffer = io.BytesIO()
    dataset.save_as(buffer, enforce_file_format=True)
    return buffer.getvalue()


def _docx_bytes(paragraphs=("Referral letter", "Patient seen today.")):
    docx = pytest.importorskip("docx")

    document = docx.Document()
    document.add_heading("Discharge summary", level=1)
    for text in paragraphs:
        document.add_paragraph(text)
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Test"
    table.cell(0, 1).text = "Result"
    table.cell(1, 0).text = "Troponin"
    table.cell(1, 1).text = "0.01"

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _upload(client, application_id, name, data):
    return client.post(
        f"/applications/{application_id}/files",
        files=[("files", (name, data, "application/octet-stream"))],
    ).json()[0]


# ------------------------------------------------------------------ dicom


def test_a_dicom_frame_comes_back_as_a_png(as_admin):
    application_id = _application(as_admin)
    record = _upload(as_admin, application_id, "study.dcm", _dicom_bytes())

    response = as_admin.get(f"/files/{record['id']}/image")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    # The PNG signature, so this is a real image and not an error page.
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_an_extensionless_dicom_renders_too(as_admin):
    """It is resolved to 'dcm' at upload, which is what makes it viewable."""
    application_id = _application(as_admin)
    record = _upload(as_admin, application_id, "IM000001", _dicom_bytes())

    assert as_admin.get(f"/files/{record['id']}/image").status_code == 200


def test_the_frame_count_comes_back_on_the_response(as_admin):
    application_id = _application(as_admin)
    record = _upload(as_admin, application_id, "study.dcm", _dicom_bytes(frames=4))

    response = as_admin.get(f"/files/{record['id']}/image")

    assert response.headers["X-Frame-Count"] == "4"


def test_each_frame_of_a_multi_frame_study_is_reachable(as_admin):
    application_id = _application(as_admin)
    record = _upload(as_admin, application_id, "study.dcm", _dicom_bytes(frames=3))

    for frame in range(3):
        response = as_admin.get(
            f"/files/{record['id']}/image", params={"frame": frame}
        )
        assert response.status_code == 200, frame


def test_a_frame_that_does_not_exist_is_rejected(as_admin):
    application_id = _application(as_admin)
    record = _upload(as_admin, application_id, "study.dcm", _dicom_bytes())

    response = as_admin.get(f"/files/{record['id']}/image", params={"frame": 7})

    assert response.status_code == 422
    assert "frame" in response.json()["error"]["detail"].lower()


def test_monochrome1_is_inverted_so_it_is_not_shown_as_a_negative(as_admin):
    """MONOCHROME1 counts white as zero. Rendered as-is it looks inverted."""
    from PIL import Image

    application_id = _application(as_admin)
    normal = _upload(
        as_admin, application_id, "a.dcm", _dicom_bytes(photometric="MONOCHROME2")
    )
    inverted = _upload(
        as_admin, application_id, "b.dcm", _dicom_bytes(photometric="MONOCHROME1")
    )

    def first_pixel(record):
        content = as_admin.get(f"/files/{record['id']}/image").content
        return Image.open(io.BytesIO(content)).convert("L").getpixel((0, 0))

    # The same gradient, so one must be the other's complement.
    assert first_pixel(normal) != first_pixel(inverted)


def test_a_pdf_is_not_offered_as_an_image(as_admin):
    application_id = _application(as_admin)
    record = _upload(as_admin, application_id, "scan.pdf", b"%PDF-1.4 fake")

    assert as_admin.get(f"/files/{record['id']}/image").status_code == 422


def test_a_dicom_with_no_pixels_says_so(as_admin):
    """A structured report is a valid DICOM with nothing to display."""
    pytest.importorskip("pydicom")
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian

    dataset = Dataset()
    dataset.PatientID = "MRN4471"
    dataset.file_meta = FileMetaDataset()
    dataset.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    dataset.file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.88.11"
    dataset.file_meta.MediaStorageSOPInstanceUID = "1.2.3.4"
    buffer = io.BytesIO()
    dataset.save_as(buffer, enforce_file_format=True)

    application_id = _application(as_admin)
    record = _upload(as_admin, application_id, "report.dcm", buffer.getvalue())

    response = as_admin.get(f"/files/{record['id']}/image")

    assert response.status_code == 422
    assert "no image data" in response.json()["error"]["detail"]


# ------------------------------------------------------------------- word


def test_a_word_document_comes_back_as_text(as_admin):
    application_id = _application(as_admin)
    record = _upload(as_admin, application_id, "letter.docx", _docx_bytes())

    response = as_admin.get(f"/files/{record['id']}/text")

    assert response.status_code == 200
    body = response.json()

    texts = [block["text"] for block in body["blocks"]]
    assert "Referral letter" in texts
    assert "Patient seen today." in texts


def test_headings_are_marked_as_headings(as_admin):
    application_id = _application(as_admin)
    record = _upload(as_admin, application_id, "letter.docx", _docx_bytes())

    blocks = as_admin.get(f"/files/{record['id']}/text").json()["blocks"]

    heading = next(b for b in blocks if b["text"] == "Discharge summary")
    assert heading["kind"] == "heading"


def test_tables_survive_as_rows_and_cells(as_admin):
    application_id = _application(as_admin)
    record = _upload(as_admin, application_id, "letter.docx", _docx_bytes())

    tables = as_admin.get(f"/files/{record['id']}/text").json()["tables"]

    assert tables == [[["Test", "Result"], ["Troponin", "0.01"]]]


def test_blank_paragraphs_are_dropped(as_admin):
    application_id = _application(as_admin)
    record = _upload(
        as_admin, application_id, "letter.docx", _docx_bytes(paragraphs=("", "  ", "real"))
    )

    blocks = as_admin.get(f"/files/{record['id']}/text").json()["blocks"]

    assert [b["text"] for b in blocks if b["kind"] == "paragraph"] == ["real"]


def test_a_dicom_is_not_offered_as_text(as_admin):
    application_id = _application(as_admin)
    record = _upload(as_admin, application_id, "study.dcm", _dicom_bytes())

    assert as_admin.get(f"/files/{record['id']}/text").status_code == 422


def test_a_legacy_doc_says_why_it_cannot_be_previewed(as_admin):
    """python-docx reads only the 2007+ format; the message has to say so
    rather than just failing."""
    from app.filetype import OLE_MAGIC

    application_id = _application(as_admin)
    record = _upload(as_admin, application_id, "old.doc", OLE_MAGIC + b"\x00" * 512)

    response = as_admin.get(f"/files/{record['id']}/text")

    assert response.status_code == 422
    assert ".docx" in response.json()["error"]["detail"]


# ------------------------------------------------------------ permissions


def test_previews_need_the_application_view_permission(client, as_admin):
    application_id = _application(as_admin)
    record = _upload(as_admin, application_id, "study.dcm", _dicom_bytes())

    client.headers.update({"REMOTE-USER": "nobody"})
    assert client.get(f"/files/{record['id']}/image").status_code == 403
    assert client.get(f"/files/{record['id']}/text").status_code == 403


def test_the_library_preview_refuses_a_file_with_no_redacted_copy(as_admin):
    application_id = _application(as_admin)
    record = _upload(as_admin, application_id, "study.dcm", _dicom_bytes())

    response = as_admin.get(f"/files-library/{record['id']}/image")

    assert response.status_code == 422
    assert "not been de-identified" in response.json()["error"]["detail"]


def test_the_library_renders_the_redacted_dicom(as_admin, tmp_path):
    application_id = _application(as_admin)
    record = _upload(as_admin, application_id, "study.dcm", _dicom_bytes())

    redacted = pathlib.Path(record["file_path"]).parent / "redacted.dcm"
    redacted.write_bytes(_dicom_bytes())
    as_admin.put(
        f"/files/{record['id']}",
        json={"deid_status": "done", "de_identified_file_path": str(redacted)},
    )

    response = as_admin.get(f"/files-library/{record['id']}/image")

    assert response.status_code == 200
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"
