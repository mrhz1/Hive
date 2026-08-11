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


IDENTIFYING_TAGS = (
    "PatientName",
    "PatientID",
    "PatientBirthDate",
    "PatientTelephoneNumbers",
    "ReferringPhysicianName",
    "InstitutionName",
    "AccessionNumber",
)


def test_dicom_identifying_tags_keep_the_field_but_lose_the_value():
    """The tag stays so the study is still a well-formed DICOM; what it
    held does not. Deleting it outright lost the fact that the field was
    ever populated, and told a reader nothing about why it is empty."""
    from deid.dicom_io import scrub_metadata

    dataset = _dataset()
    before = {
        tag: str(dataset[tag].value) for tag in IDENTIFYING_TAGS if tag in dataset
    }
    assert before, "the fixture should populate some identifying tags"

    scrub_metadata(dataset)

    for tag, original in before.items():
        assert tag in dataset, f"{tag} was deleted rather than de-identified"
        now = str(dataset[tag].value)
        assert now != original, f"{tag} kept its value"
        assert original not in now, f"{tag} still contains the original"


def test_dicom_without_an_analyzer_still_removes_every_value():
    """No analyzer to call is not a reason to leave PHI in place: the
    known tags are replaced regardless of what any model thinks."""
    from deid.dicom_io import scrub_metadata

    dataset = _dataset()
    scrub_metadata(dataset, redact=None)

    for tag in IDENTIFYING_TAGS:
        if tag in dataset:
            value = str(dataset[tag].value)
            assert value in ("", "<REMOVED>"), f"{tag} = {value!r}"


def test_dicom_de_identifies_a_tag_no_deny_list_covers():
    """StudyDescription is on no list, and used to survive intact. The
    clinical part of it should still survive; the name should not."""
    from deid.dicom_io import scrub_metadata

    dataset = _dataset()
    dataset.StudyDescription = "MRI BRAIN - JANE DOE"

    scrub_metadata(dataset, redact=lambda text: text.replace("JANE DOE", "<PERSON>"))

    assert dataset.StudyDescription == "MRI BRAIN - <PERSON>"


def test_dicom_keeps_what_does_not_identify_anyone():
    from deid.dicom_io import scrub_metadata

    dataset = _dataset()
    dataset.Modality = "MR"
    dataset.Manufacturer = "SIEMENS"

    scrub_metadata(dataset, redact=lambda text: text)

    assert dataset.Modality == "MR"
    assert dataset.Manufacturer == "SIEMENS"


def test_dicom_stays_decodable_however_eager_the_analyzer_is():
    """The reported bug: the analyzer called 'MONOCHROME2' a person, so
    PhotometricInterpretation became '<PERSON>' and the study would not
    render at all -- 'pixel data could not be decoded'.

    Coded values are matched against enumerations, never read, so there
    is nothing in them to de-identify.
    """
    from deid.dicom_io import scrub_metadata

    dataset = _dataset()

    # An analyzer that tags absolutely everything, which is the worst
    # case this has to survive.
    scrub_metadata(dataset, redact=lambda text: "<PERSON>")

    assert dataset.PhotometricInterpretation == "MONOCHROME2"
    assert int(dataset.Rows) > 0
    assert int(dataset.Columns) > 0
    assert int(dataset.BitsAllocated) == 8
    assert int(dataset.SamplesPerPixel) == 1
    # The whole point: it still decodes.
    assert dataset.pixel_array.shape == (dataset.Rows, dataset.Columns)


def test_dicom_codes_are_left_alone():
    """Modality is a CS code. '<PERSON>' is not a modality."""
    from deid.dicom_io import scrub_metadata

    dataset = _dataset()
    dataset.Modality = "MR"

    scrub_metadata(dataset, redact=lambda text: "<PERSON>")

    assert dataset.Modality == "MR"


def test_dicom_free_text_is_still_redacted_under_the_same_analyzer():
    """The narrowing must not have switched redaction off everywhere."""
    from deid.dicom_io import scrub_metadata

    dataset = _dataset()
    dataset.StudyDescription = "MRI BRAIN - JANE DOE"

    scrub_metadata(dataset, redact=lambda text: text.replace("JANE DOE", "<PERSON>"))

    assert dataset.StudyDescription == "MRI BRAIN - <PERSON>"


def test_dicom_dates_are_emptied_rather_than_tagged():
    """'<DATE>' is not a valid DA value; a reader parsing it would choke."""
    from deid.dicom_io import scrub_metadata

    dataset = _dataset()
    dataset.StudyDate = "20240103"

    scrub_metadata(dataset, redact=lambda text: "<DATE>")

    assert dataset.StudyDate == ""
    assert dataset.PatientBirthDate == ""


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
    assert "Doe" not in str(reread.PatientName)
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


# ------------------------------------- de-identifying, rather than wiping


def _name_redactor(text: str) -> str:
    """Stands in for the analyzer, with its judgement made predictable."""
    for name in ("Jane Doe", "Alan Grant"):
        text = text.replace(name, "<PERSON>")
    return text.replace("555-0142", "<PHONE_NUMBER>")


def test_word_properties_keep_their_shape_when_de_identified():
    from deid.docx_io import deidentify_properties

    document = _document()
    document.core_properties.keywords = "cardiology"

    deidentify_properties(document, _name_redactor)

    properties = document.core_properties
    # The name goes; what the document is stays.
    assert properties.title == "Referral for <PERSON>"
    assert properties.comments == "Contact <PHONE_NUMBER>"
    # Not identifying, so not touched.
    assert properties.keywords == "cardiology"


def test_word_authorship_never_keeps_its_own_value():
    """`author` names a person by definition. If the analyzer finds
    nothing in it, that is a miss, not a clean bill of health."""
    from deid.docx_io import deidentify_properties

    document = _document()
    document.core_properties.author = "asdf qwerty"

    deidentify_properties(document, lambda text: text)

    assert document.core_properties.author == "<REMOVED>"


def test_word_de_identification_leaves_nothing_on_disk(tmp_path):
    from deid.docx_io import deidentify_properties, redact_document, save_docx

    document = _document()
    redact_document(document, _name_redactor)
    deidentify_properties(document, _name_redactor)

    out = tmp_path / "out.docx"
    save_docx(document, str(out))

    raw = _stored_xml(out)
    assert "Jane Doe" not in raw
    assert "Alan Grant" not in raw
    assert "555-0142" not in raw


def test_pdf_info_is_de_identified_rather_than_emptied():
    """Emptying the dictionary took 'Producer: Acme Scanner' with it, and
    that identifies nobody."""
    import fitz

    document = fitz.open()
    document.new_page()
    document.set_metadata(
        {
            "author": "Alan Grant",
            "title": "Referral for Jane Doe",
            "producer": "Acme Scanner 4.1",
        }
    )

    documents.scrub_metadata(document, documents.PDF, _name_redactor)
    info = document.metadata
    document.close()

    assert info["author"] == "<PERSON>"
    assert info["title"] == "Referral for <PERSON>"
    assert info["producer"] == "Acme Scanner 4.1"


def test_pdf_author_never_keeps_its_own_value():
    import fitz

    document = fitz.open()
    document.new_page()
    document.set_metadata({"author": "asdf qwerty"})

    documents.scrub_metadata(document, documents.PDF, lambda text: text)
    info = document.metadata
    document.close()

    assert info["author"] == "<REMOVED>"


def test_pdf_without_an_analyzer_still_empties_everything():
    import fitz

    document = fitz.open()
    document.new_page()
    document.set_metadata({"author": "Alan Grant", "title": "Referral"})

    documents.scrub_metadata(document, documents.PDF)
    info = document.metadata
    document.close()

    assert not info.get("author")
    assert not info.get("title")
