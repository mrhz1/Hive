"""Recognising a document by its bytes when the name does not say.

The case that drove this: a DICOM off a PACS arrives as `IM000001` with
no extension at all, which left it un-de-identifiable (the button was
disabled), unread for metadata, and headed for DEID_PDF_DIR.
"""
import pathlib

import pytest
from conftest import minimal_patient

from app.filetype import resolve_extension, sniff_extension

DICOM_BYTES = b"\0" * 128 + b"DICM" + b"\x02\x00\x00\x00UL\x04\x00"

PDF_BYTES = b"%PDF-1.4 fake"

# A minimal zip whose first entry names a word/ path, as a .docx does.
DOCX_BYTES = b"PK\x03\x04" + b"\x14\x00" * 6 + b"[Content_Types].xml word/document.xml"

OLE_BYTES = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 32


# ------------------------------------------------------------- sniffing


@pytest.mark.parametrize(
    "head,expected",
    [
        (DICOM_BYTES, "dcm"),
        (b"DICM" + b"\0" * 32, "dcm"),  # preamble-less writers
        (PDF_BYTES, "pdf"),
        (DOCX_BYTES, "docx"),
        (OLE_BYTES, "doc"),
        (b"just some notes", None),
        (b"", None),
        (b"PK\x03\x04 nothing wordy here", None),  # a zip that is not a .docx
    ],
)
def test_sniffing_reads_the_format_off_the_bytes(head, expected):
    assert sniff_extension(head) == expected


def test_a_name_that_names_a_handled_format_is_believed():
    # .dcm vs .dicom and .doc vs .docx are distinctions the magic numbers
    # cannot make, so a name that carries one wins.
    assert resolve_extension("study.dicom", DICOM_BYTES) == "dicom"
    assert resolve_extension("letter.doc", OLE_BYTES) == "doc"


def test_the_bytes_decide_when_the_name_says_nothing():
    assert resolve_extension("IM000001", DICOM_BYTES) == "dcm"
    assert resolve_extension("1.2.840.113619.2", DICOM_BYTES) == "dcm"


def test_the_bytes_decide_when_the_name_is_wrong():
    """A PDF called .txt is still a PDF, and still has to be redactable."""
    assert resolve_extension("notes.txt", PDF_BYTES) == "pdf"


def test_an_unrecognised_file_keeps_whatever_its_name_claimed():
    assert resolve_extension("notes.txt", b"just some notes") == "txt"
    assert resolve_extension("mystery", b"\x00\x01\x02") == ""


# --------------------------------------------------------- through the API


def _patient_and_application(client):
    patient_id = client.post("/patients", json=minimal_patient()).json()["id"]
    application_id = client.post(
        "/applications", json={"patient_id": patient_id}
    ).json()["id"]
    return patient_id, application_id


def _upload(client, application_id, name, data, endpoint="files"):
    return client.post(
        f"/applications/{application_id}/{endpoint}",
        files=[("files", (name, data, "application/octet-stream"))],
    )


def test_an_extensionless_dicom_can_be_de_identified(as_admin, storage_root):
    """The reported bug: the De-identify button was disabled, because the
    row said the file had no extension at all."""
    _, application_id = _patient_and_application(as_admin)

    record = _upload(as_admin, application_id, "IM000001", DICOM_BYTES).json()[0]

    assert record["file_extension"] == "dcm"

    from app.deid import is_deidentifiable

    assert is_deidentifiable(record["file_extension"])


def test_an_extensionless_dicom_lands_in_the_dicom_folder_name(
    as_admin, storage_root
):
    patient_id, application_id = _patient_and_application(as_admin)

    record = _upload(as_admin, application_id, "IM000001", DICOM_BYTES).json()[0]

    stored = pathlib.Path(record["file_path"])
    # <patient>-dicom-<serial>.dcm, not <patient>-file-<serial>
    assert stored.name.startswith(f"{patient_id}-dicom-")
    assert stored.suffix == ".dcm"


def test_an_extensionless_dicom_files_to_the_dicom_directory(
    as_admin, storage_root
):
    """deid_dir_for('') falls back to the PDF directory, so before this
    an extensionless DICOM would have been filed with the PDFs."""
    from app.storage import DEID_DICOM_DIR, deid_dir_for

    _, application_id = _patient_and_application(as_admin)
    record = _upload(as_admin, application_id, "IM000001", DICOM_BYTES).json()[0]

    assert deid_dir_for(record["file_extension"]) == DEID_DICOM_DIR


def test_the_background_upload_sniffs_the_same_way(
    as_admin, storage_root, sent_emails
):
    _, application_id = _patient_and_application(as_admin)

    _upload(as_admin, application_id, "IM000001", DICOM_BYTES, "files/background")

    listed = as_admin.get(f"/applications/{application_id}/files").json()
    assert [record["file_extension"] for record in listed] == ["dcm"]


def test_metadata_is_extracted_from_an_extensionless_dicom(
    as_admin, storage_root
):
    """Unread before: file_type_for('') is None, so the row said
    'unsupported' and carried no fields."""
    _, application_id = _patient_and_application(as_admin)

    record = _upload(as_admin, application_id, "IM000001", DICOM_BYTES).json()[0]

    metadata = as_admin.get(f"/files/{record['id']}/metadata").json()
    assert metadata["file_type"] == "dicom"
    assert metadata["status"] != "unsupported"
