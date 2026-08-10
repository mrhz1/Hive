"""DICOM and Word de-identification, without the ML stack."""
import sys
from pathlib import Path

import pytest

OCR_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(OCR_ROOT))

numpy = pytest.importorskip("numpy", reason="needs the OCR/NLP virtualenv")
pydicom = pytest.importorskip("pydicom", reason="needs the OCR/NLP virtualenv")
docx = pytest.importorskip("docx", reason="needs the OCR/NLP virtualenv")

from deid import documents  # noqa: E402
from deid.spans import RedactionBox  # noqa: E402


# ------------------------------------------------------------- dispatch

@pytest.mark.parametrize(
    "name,kind,ocr,extension",
    [
        ("a.pdf", "pdf", True, ".pdf"),
        ("a.PDF", "pdf", True, ".pdf"),
        ("b.dcm", "dicom", True, ".dcm"),
        ("b.dicom", "dicom", True, ".dcm"),
        ("c.docx", "docx", False, ".docx"),
        ("c.doc", "docx", False, ".docx"),
    ],
)
def test_format_dispatch(name, kind, ocr, extension):
    assert documents.kind_for(name) == kind
    assert documents.needs_ocr(name) is ocr
    assert documents.output_extension(name) == extension


def test_unsupported_formats_are_not_claimed():
    for name in ("scan.jpg", "notes.txt", "sheet.xlsx", "noextension"):
        assert documents.kind_for(name) == ""
        assert documents.is_supported(name) is False


# ---------------------------------------------------------------- DICOM

def _dataset(rows=64, cols=128, value=200):
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid

    dataset = Dataset()
    dataset.PatientName = "Jane Doe"
    dataset.PatientID = "MRN4471203"
    dataset.PatientBirthDate = "19780414"
    dataset.PatientTelephoneNumbers = "555-0142"
    dataset.ReferringPhysicianName = "Dr Alan Grant"
    dataset.InstitutionName = "St Elsewhere General"
    dataset.AccessionNumber = "ACC00099"
    dataset.StudyDate = "20260101"
    dataset.Modality = "OT"

    block = dataset.private_block(0x000B, "HIVE TEST", create=True)
    block.add_new(0x01, "LO", "Jane Doe")

    dataset.SamplesPerPixel = 1
    dataset.PhotometricInterpretation = "MONOCHROME2"
    dataset.Rows = rows
    dataset.Columns = cols
    dataset.BitsAllocated = 8
    dataset.BitsStored = 8
    dataset.HighBit = 7
    dataset.PixelRepresentation = 0
    dataset.PixelData = numpy.full((rows, cols), value, dtype=numpy.uint8).tobytes()

    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.7"
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.ImplementationClassUID = generate_uid()
    dataset.file_meta = meta
    dataset.SOPClassUID = meta.MediaStorageSOPClassUID
    dataset.SOPInstanceUID = meta.MediaStorageSOPInstanceUID

    return dataset


def test_dicom_identifying_tags_are_removed():
    from deid.dicom_io import scrub_metadata

    dataset = _dataset()
    scrub_metadata(dataset)

    for tag in (
        "PatientName",
        "PatientID",
        "PatientBirthDate",
        "PatientTelephoneNumbers",
        "ReferringPhysicianName",
        "InstitutionName",
        "AccessionNumber",
    ):
        assert tag not in dataset, f"{tag} survived"


def test_dicom_private_tags_are_removed():
    """Vendor-private tags are undocumented and have been found holding names, so they go wholesale rather than by inspection."""
    from deid.dicom_io import scrub_metadata

    dataset = _dataset()
    assert [e for e in dataset if e.tag.is_private]

    scrub_metadata(dataset)

    assert [e for e in dataset if e.tag.is_private] == []


def test_dicom_dates_are_blanked_not_deleted():
    """Deleting them outright makes some viewers reject the file."""
    from deid.dicom_io import scrub_metadata

    dataset = _dataset()
    scrub_metadata(dataset)

    assert "StudyDate" in dataset
    assert dataset.StudyDate == ""


def test_dicom_says_it_has_been_deidentified():
    from deid.dicom_io import scrub_metadata

    dataset = _dataset()
    scrub_metadata(dataset)

    assert dataset.PatientIdentityRemoved == "YES"
    assert dataset.DeidentificationMethod


def test_dicom_pixels_are_actually_painted():
    from deid.dicom_io import apply_redactions

    dataset = _dataset(rows=64, cols=128, value=200)
    box = RedactionBox(x0=10, y0=10, x1=50, y1=30, entity_type="PERSON", score=0.9)

    applied = apply_redactions(dataset, 1, [box], scale=1.0, fill="black")

    assert applied == 1
    pixels = dataset.pixel_array
    assert pixels[10:30, 10:50].max() == 0, "the box was not blacked out"
    assert pixels[0:5, 0:5].min() == 200, "pixels outside the box changed"


def test_dicom_box_outside_the_frame_is_skipped_not_wrapped():
    """A negative or oversized box must not silently wrap around the array and blank the wrong region."""
    from deid.dicom_io import apply_redactions

    dataset = _dataset(rows=64, cols=128, value=200)
    outside = RedactionBox(
        x0=500, y0=500, x1=600, y1=600, entity_type="PERSON", score=0.9
    )

    applied = apply_redactions(dataset, 1, [outside], scale=1.0)

    assert applied == 0
    assert dataset.pixel_array.min() == 200


def test_dicom_round_trips_through_disk(tmp_path):
    from deid.dicom_io import apply_redactions, save_dicom, scrub_metadata

    dataset = _dataset()
    apply_redactions(
        dataset,
        1,
        [RedactionBox(x0=0, y0=0, x1=20, y1=20, entity_type="PERSON", score=1.0)],
        scale=1.0,
    )
    scrub_metadata(dataset)

    out = tmp_path / "out.dcm"
    save_dicom(dataset, str(out))

    reread = pydicom.dcmread(str(out))
    assert "PatientName" not in reread
    assert reread.pixel_array[0:20, 0:20].max() == 0
    assert reread.PatientIdentityRemoved == "YES"


# ----------------------------------------------------------------- Word

def _document():
    document = docx.Document()
    document.add_paragraph("Patient Jane Doe, born 1978-04-14.")

    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Name"
    table.cell(0, 1).text = "Jane Doe"

    section = document.sections[0]
    section.header.paragraphs[0].text = "Jane Doe - MRN4471203"
    section.footer.paragraphs[0].text = "St Elsewhere General"

    properties = document.core_properties
    properties.author = "Dr Alan Grant"
    properties.last_modified_by = "Dr Alan Grant"
    properties.title = "Referral for Jane Doe"
    properties.comments = "Contact 555-0142"

    return document


def test_word_traversal_reaches_tables_headers_and_footers():
    """Body-only redaction is the usual miss: a patient banner lives in the header and the MRN in a table."""
    from deid.docx_io import read_blocks

    texts = [text for _, text in read_blocks(_document())]

    assert any("Patient Jane Doe" in t for t in texts), "body paragraph missed"
    assert any(t == "Jane Doe" for t in texts), "table cell missed"
    assert any("MRN4471203" in t for t in texts), "header missed"
    assert any("St Elsewhere" in t for t in texts), "footer missed"


def test_word_redaction_replaces_characters_everywhere():
    from deid.docx_io import paragraphs, read_blocks, redact_document

    document = _document()
    redact_document(document, lambda text: text.replace("Jane Doe", "[REDACTED]"))

    full = "\n".join(p.text for p in paragraphs(document))
    assert "Jane Doe" not in full
    assert "[REDACTED]" in full
    assert "MRN4471203" in full
    assert len(read_blocks(document)) == 5


def _stored_xml(path) -> str:
    """Every XML part of a .docx, concatenated. What is actually on disk."""
    import zipfile

    with zipfile.ZipFile(path) as archive:
        return b" ".join(
            archive.read(name) for name in archive.namelist() if name.endswith(".xml")
        ).decode("utf-8", "ignore")


def test_word_redacting_the_body_alone_leaves_phi_in_the_properties(tmp_path):
    """Why scrub_metadata is not optional."""
    from deid.docx_io import redact_document, save_docx

    document = _document()
    redact_document(document, lambda text: text.replace("Jane Doe", "[REDACTED]"))

    out = tmp_path / "body-only.docx"
    save_docx(document, str(out))

    assert "Jane Doe" in _stored_xml(out)


def test_word_redaction_and_scrub_leave_nothing_on_disk(tmp_path):
    """The full sequence the pipeline runs."""
    from deid.docx_io import clear_properties, redact_document, save_docx

    document = _document()
    redact_document(document, lambda text: text.replace("Jane Doe", "[REDACTED]"))
    clear_properties(document)

    out = tmp_path / "out.docx"
    save_docx(document, str(out))

    raw = _stored_xml(out)
    assert "Jane Doe" not in raw
    assert "Alan Grant" not in raw
    assert "555-0142" not in raw


def test_word_properties_are_cleared():
    from deid.docx_io import clear_properties

    document = _document()
    cleared = clear_properties(document)

    properties = document.core_properties
    assert properties.author == ""
    assert properties.last_modified_by == ""
    assert properties.title == ""
    assert properties.comments == ""
    assert set(cleared) >= {"author", "last_modified_by", "title", "comments"}


def test_word_properties_are_cleared_through_the_dispatcher():
    document = _document()

    documents.scrub_metadata(document, documents.DOCX)

    assert document.core_properties.author == ""
