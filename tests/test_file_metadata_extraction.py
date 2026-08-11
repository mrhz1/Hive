"""Reading what a document arrived carrying.

This is the half that lands in `file_metadata`. What the system works out
afterwards goes into the output file instead -- test_deid_metadata.py.
"""
import pathlib

import pytest

from app.file_metadata import extract
from app.filetype import OLE_MAGIC


def _dicom(path: pathlib.Path, **attributes):
    pydicom = pytest.importorskip("pydicom")
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian

    dataset = Dataset()
    for name, value in attributes.items():
        setattr(dataset, name, value)
    dataset.file_meta = FileMetaDataset()
    dataset.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    dataset.file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.7"
    dataset.file_meta.MediaStorageSOPInstanceUID = "1.2.3.4"
    dataset.save_as(str(path), enforce_file_format=True)
    return path


# ------------------------------------------------------------------ dicom


def test_a_dicom_gives_up_its_tags(tmp_path):
    path = _dicom(
        tmp_path / "im.dcm",
        PatientName="Doe^Jane",
        PatientID="MRN4471",
        Modality="CT",
        StudyDescription="CHEST W/O CONTRAST",
        Manufacturer="SIEMENS",
    )

    file_type, metadata, status, error = extract(path, "dcm")

    assert (file_type, status, error) == ("dicom", "ok", None)
    assert metadata["PatientID"] == "MRN4471"
    assert metadata["Modality"] == "CT"
    assert metadata["StudyDescription"] == "CHEST W/O CONTRAST"


def test_a_dicom_read_by_content_not_by_name(tmp_path):
    """An extensionless DICOM is resolved to 'dcm' at upload, so by the
    time extraction runs the format is known."""
    path = _dicom(tmp_path / "IM000001", PatientID="MRN4471")

    _, metadata, status, _ = extract(path, "dcm")

    assert status == "ok"
    assert metadata["PatientID"] == "MRN4471"


def test_pixel_data_is_not_dragged_into_the_row(tmp_path):
    path = _dicom(tmp_path / "im.dcm", PatientID="MRN4471")

    _, metadata, _, _ = extract(path, "dcm")

    assert "PixelData" not in metadata


# ------------------------------------------------------------------- word


def test_a_docx_gives_up_its_core_properties(tmp_path):
    docx = pytest.importorskip("docx")

    path = tmp_path / "letter.docx"
    document = docx.Document()
    document.add_paragraph("body")
    document.core_properties.author = "Dr Grant"
    document.core_properties.title = "Referral"
    document.save(str(path))

    file_type, metadata, status, _ = extract(path, "docx")

    assert (file_type, status) == ("word", "ok")
    assert metadata["author"] == "Dr Grant"
    assert metadata["title"] == "Referral"


class _FakeProperties:
    """Stands in for olefile's OleMetadata."""

    SUMMARY_ATTRIBS = ["title", "author", "last_saved_by", "num_pages"]
    DOCSUM_ATTRIBS = ["company", "category"]

    title = b"Discharge summary\x00"      # olefile hands back bytes here
    author = "Dr Grant"
    last_saved_by = "M Lapinsky"
    num_pages = 4
    company = "St Mary's"
    category = None                        # unset properties are dropped


class _FakeOle:
    def __init__(self, path):
        self.path = path

    def get_metadata(self):
        return _FakeProperties()

    def close(self):
        self.closed = True


def test_a_legacy_doc_is_read_through_its_ole_streams(tmp_path, monkeypatch):
    """python-docx reads only the 2007+ zip format, so before this every
    pre-2007 .doc recorded 'failed' and no metadata at all.

    Verified against a genuine Word 97 document as well as this stub: 26
    fields, including author, template and creating_application.
    """
    olefile = pytest.importorskip("olefile")
    monkeypatch.setattr(olefile, "OleFileIO", _FakeOle)

    path = tmp_path / "old.doc"
    path.write_bytes(OLE_MAGIC + b"\x00" * 512)

    file_type, metadata, status, error = extract(path, "doc")

    assert (file_type, status, error) == ("word", "ok", None)
    assert metadata["title"] == "Discharge summary"   # bytes decoded, NUL stripped
    assert metadata["author"] == "Dr Grant"
    assert metadata["company"] == "St Mary's"
    assert metadata["num_pages"] == "4"
    assert "category" not in metadata                 # unset, so not stored


def test_the_container_decides_which_word_reader_runs(tmp_path, monkeypatch):
    """A .docx misnamed .doc still reads, and vice versa -- the OLE2
    signature is what picks the reader, not the extension."""
    docx = pytest.importorskip("docx")

    path = tmp_path / "actually_a_docx.doc"
    document = docx.Document()
    document.core_properties.author = "Dr Grant"
    document.save(str(path))

    _, metadata, status, _ = extract(path, "doc")

    assert status == "ok"
    assert metadata["author"] == "Dr Grant"


def test_a_word_file_that_is_neither_records_the_failure(tmp_path):
    path = tmp_path / "broken.docx"
    path.write_bytes(b"not a document at all")

    file_type, metadata, status, error = extract(path, "docx")

    assert (file_type, status) == ("word", "failed")
    assert metadata == {}
    assert error


# -------------------------------------------------------------------- pdf


def test_a_pdf_gives_up_its_info_dictionary(tmp_path):
    fitz = pytest.importorskip("fitz")

    path = tmp_path / "scan.pdf"
    document = fitz.open()
    document.new_page()
    document.set_metadata({"author": "Dr Grant", "title": "Referral"})
    document.save(str(path))
    document.close()

    file_type, metadata, status, _ = extract(path, "pdf")

    assert (file_type, status) == ("pdf", "ok")
    assert metadata["author"] == "Dr Grant"
    assert metadata["page_count"] == "1"


def test_an_unhandled_format_is_unsupported_not_failed(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("hello")

    file_type, metadata, status, error = extract(path, "txt")

    assert (file_type, status, error) == ("txt", "unsupported", None)
    assert metadata == {}
