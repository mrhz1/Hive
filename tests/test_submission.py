"""Submitting an application stamps and files its de-identified output."""
import pathlib

import fitz
import pytest

from app import storage, submission
from conftest import minimal_patient


@pytest.fixture
def deid_dirs(tmp_path, monkeypatch):
    """Point every configured destination at a temp directory."""
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


def _pdf(path: pathlib.Path, pages: int = 2) -> pathlib.Path:
    document = fitz.open()
    for number in range(pages):
        page = document.new_page()
        page.insert_text(fitz.Point(200, 400), f"clinical content {number}")
    path.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(path))
    document.close()
    return path


def _submitted_application(client, storage_root, name="scan.pdf"):
    """A patient, an application, and one file already de-identified."""
    patient_id = client.post("/patients", json=minimal_patient()).json()["id"]
    application_id = client.post(
        "/applications", json={"patient_id": patient_id}
    ).json()["id"]
    record = client.post(
        f"/applications/{application_id}/files",
        files=[("files", (name, b"%PDF-1.4 fake", "application/pdf"))],
    ).json()[0]
    return patient_id, application_id, record


def _stage_output(record, storage_root, extension="pdf", pages=2):
    """Put a de-identified file where the pipeline would have left it."""
    original = pathlib.Path(record["file_path"])
    staged = original.parent / "deidentified" / f"{original.stem}_deid.{extension}"
    if extension == "pdf":
        _pdf(staged, pages=pages)
    else:
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(b"redacted bytes")
    return staged


def test_submitting_stamps_and_files_the_pdf(
    as_admin, storage_root, deid_dirs, monkeypatch
):
    patient_id, application_id, record = _submitted_application(as_admin, storage_root)
    staged = _stage_output(record, storage_root, pages=3)

    as_admin.put(
        f"/files/{record['id']}",
        json={
            "deid_status": "done",
            "is_deidentified": True,
            "de_identified_file_path": str(staged),
            "deidentified_file_name": staged.name,
        },
    )

    submission.finalise_submission(application_id)

    final = deid_dirs["pdf"] / patient_id / staged.name
    assert final.is_file(), "output was not moved to the configured location"
    assert not staged.exists(), "the staging copy was left behind"

    document = fitz.open(str(final))
    assert document.page_count == 3
    for page in document:
        words = page.get_text("words")
        stamps = [w for w in words if w[4] == patient_id]
        assert len(stamps) == 1, f"page {page.number} is not stamped"
        # Top-left: x near the left edge, y near the top.
        assert stamps[0][0] < page.rect.width / 3
        assert stamps[0][1] < page.rect.height / 3
        assert any("clinical" in w[4] for w in words), "content was lost"
    document.close()


def test_the_row_points_at_the_final_location(
    as_admin, storage_root, deid_dirs
):
    patient_id, application_id, record = _submitted_application(as_admin, storage_root)
    staged = _stage_output(record, storage_root)

    as_admin.put(
        f"/files/{record['id']}",
        json={"deid_status": "done", "de_identified_file_path": str(staged)},
    )

    submission.finalise_submission(application_id)

    after = as_admin.get(f"/files/{record['id']}").json()
    assert after["de_identified_file_path"] == str(deid_dirs["pdf"] / patient_id / staged.name)


def test_dicom_goes_to_the_dicom_directory_and_is_not_stamped(
    as_admin, storage_root, deid_dirs
):
    """Stamping is a PDF operation; a DICOM would be corrupted by it."""
    patient_id = as_admin.post("/patients", json=minimal_patient()).json()["id"]
    application_id = as_admin.post(
        "/applications", json={"patient_id": patient_id}
    ).json()["id"]
    record = as_admin.post(
        f"/applications/{application_id}/files",
        files=[("files", ("study.dcm", b"DICM fake", "application/dicom"))],
    ).json()[0]

    staged = _stage_output(record, storage_root, extension="dcm")
    as_admin.put(
        f"/files/{record['id']}",
        json={"deid_status": "done", "de_identified_file_path": str(staged)},
    )

    submission.finalise_submission(application_id)

    final = deid_dirs["dicom"] / patient_id / staged.name
    assert final.is_file()
    assert final.read_bytes() == b"redacted bytes", "a DICOM was rewritten"


def test_files_that_are_not_done_are_left_alone(as_admin, storage_root, deid_dirs):
    patient_id, application_id, record = _submitted_application(as_admin, storage_root)
    staged = _stage_output(record, storage_root)

    # Still processing: nothing to file yet.
    as_admin.put(
        f"/files/{record['id']}",
        json={"deid_status": "processing", "de_identified_file_path": str(staged)},
    )

    submission.finalise_submission(application_id)

    assert staged.is_file()
    assert not (deid_dirs["pdf"] / patient_id / staged.name).exists()


def test_a_missing_staged_file_does_not_raise(as_admin, storage_root, deid_dirs):
    """Runs detached from the request, so it records and moves on."""
    _, application_id, record = _submitted_application(as_admin, storage_root)
    original = pathlib.Path(record["file_path"])
    missing = original.parent / "deidentified" / "not-there_deid.pdf"

    as_admin.put(
        f"/files/{record['id']}",
        json={"deid_status": "done", "de_identified_file_path": str(missing)},
    )

    submission.finalise_submission(application_id)  # must not raise


def test_submitting_through_the_api_triggers_it(as_admin, storage_root, deid_dirs):
    """The whole point: the user presses Submit, this happens."""
    patient_id, application_id, record = _submitted_application(
        as_admin, storage_root
    )
    staged = _stage_output(record, storage_root)

    as_admin.put(
        f"/files/{record['id']}",
        json={"deid_status": "done", "de_identified_file_path": str(staged)},
    )

    response = as_admin.put(
        f"/applications/{application_id}", json={"status": "submitted"}
    )

    assert response.status_code == 200
    assert (deid_dirs["pdf"] / patient_id / staged.name).is_file()


def test_an_extensionless_dicom_is_filed_with_the_dicoms(
    as_admin, storage_root, deid_dirs
):
    """deid_dir_for('') falls back to the PDF directory, so an
    extensionless DICOM used to be filed with the PDFs. It is resolved to
    'dcm' at upload now, which is what routes it here."""
    from tests.test_filetype import DICOM_BYTES

    patient_id = as_admin.post("/patients", json=minimal_patient()).json()["id"]
    application_id = as_admin.post(
        "/applications", json={"patient_id": patient_id}
    ).json()["id"]
    record = as_admin.post(
        f"/applications/{application_id}/files",
        files=[("files", ("IM000001", DICOM_BYTES, "application/octet-stream"))],
    ).json()[0]

    staged = _stage_output(record, storage_root, extension="dcm")
    as_admin.put(
        f"/files/{record['id']}",
        json={"deid_status": "done", "de_identified_file_path": str(staged)},
    )

    as_admin.put(f"/applications/{application_id}", json={"status": "submitted"})

    assert (deid_dirs["dicom"] / patient_id / staged.name).is_file()
    assert not (deid_dirs["pdf"] / patient_id / staged.name).exists()


def test_re_saving_an_already_submitted_application_does_not_refile(
    as_admin, storage_root, deid_dirs
):
    """Stamping twice would put two ids on every page."""
    patient_id, application_id, record = _submitted_application(as_admin, storage_root)
    staged = _stage_output(record, storage_root)
    as_admin.put(
        f"/files/{record['id']}",
        json={"deid_status": "done", "de_identified_file_path": str(staged)},
    )

    as_admin.put(f"/applications/{application_id}", json={"status": "submitted"})
    as_admin.put(f"/applications/{application_id}", json={"status": "submitted"})

    final = deid_dirs["pdf"] / patient_id / staged.name
    document = fitz.open(str(final))
    stamps = [w for w in document[0].get_text("words") if w[4] == patient_id]
    document.close()

    assert len(stamps) == 1, "the id was stamped more than once"


def test_submitting_removes_the_identified_original(
    as_admin, storage_root, deid_dirs
):
    """The redacted copy is what survives submission. Keeping the
    identified one past that point is the risk the whole pass exists to
    remove."""
    patient_id, application_id, record = _submitted_application(
        as_admin, storage_root
    )
    original = pathlib.Path(record["file_path"])
    staged = _stage_output(record, storage_root)

    as_admin.put(
        f"/files/{record['id']}",
        json={"deid_status": "done", "de_identified_file_path": str(staged)},
    )
    assert original.is_file()

    submission.finalise_submission(application_id)

    assert not original.exists(), "the identified copy is still on disk"
    assert (deid_dirs["pdf"] / patient_id / staged.name).is_file()


def test_an_original_without_a_redacted_copy_is_kept(
    as_admin, storage_root, deid_dirs
):
    """The original is the thing that cannot be reconstructed, so it goes
    only once there is something to replace it."""
    _, application_id, record = _submitted_application(as_admin, storage_root)
    original = pathlib.Path(record["file_path"])
    staged = _stage_output(record, storage_root)

    as_admin.put(
        f"/files/{record['id']}",
        json={"deid_status": "processing", "de_identified_file_path": str(staged)},
    )

    submission.finalise_submission(application_id)

    assert original.is_file()


# ------------------------------------------------- what is left behind

def test_submitting_clears_out_the_upload_folder(
    as_admin, storage_root, deid_dirs
):
    """An upload lands in a folder of its own. Once its documents have
    been filed under the patient and the originals discarded, the folder
    is an empty shell, and they were accumulating one per upload."""
    _, application_id, record = _submitted_application(as_admin, storage_root)
    original = pathlib.Path(record["file_path"])
    staged = _stage_output(record, storage_root)

    as_admin.put(
        f"/files/{record['id']}",
        json={"deid_status": "done", "de_identified_file_path": str(staged)},
    )

    submission.finalise_submission(application_id)

    assert not original.parent.exists(), "the upload folder was left behind"


def test_submitting_takes_the_run_s_text_and_report_with_it(
    as_admin, storage_root, deid_dirs
):
    """The pipeline also writes the text it read out of the document.
    Discarding the original while leaving that behind keeps the contents
    in the clear, which is the thing submission is meant to end."""
    _, application_id, record = _submitted_application(as_admin, storage_root)
    staged = _stage_output(record, storage_root)

    text = staged.with_suffix(".txt")
    report = staged.parent / f"{staged.stem}.report.json"
    text.write_text("Jane Doe, MRN 12345")
    report.write_text("{}")

    as_admin.put(
        f"/files/{record['id']}",
        json={"deid_status": "done", "de_identified_file_path": str(staged)},
    )

    submission.finalise_submission(application_id)

    assert not text.exists(), "the extracted text survived submission"
    assert not report.exists(), "the redaction report survived submission"


def test_a_folder_still_holding_a_document_is_kept(
    as_admin, storage_root, deid_dirs
):
    """One document filed, one never de-identified. The second one's
    original stays, so the folder has to stay with it."""
    _, application_id, record = _submitted_application(as_admin, storage_root)
    other = as_admin.post(
        f"/applications/{application_id}/files",
        files=[("files", ("second.pdf", b"%PDF-1.4 fake", "application/pdf"))],
    ).json()[0]

    staged = _stage_output(record, storage_root)
    as_admin.put(
        f"/files/{record['id']}",
        json={"deid_status": "done", "de_identified_file_path": str(staged)},
    )

    submission.finalise_submission(application_id)

    kept = pathlib.Path(other["file_path"])
    assert kept.is_file(), "an un-redacted original was removed"
    assert kept.parent.is_dir()


def test_a_document_attached_already_redacted_survives_submission(
    as_admin, storage_root, deid_dirs
):
    """It has no original behind it, so both paths on the row name the
    same file. Discarding 'the original' deleted the only copy there
    was, moments after filing it."""
    patient_id = as_admin.post("/patients", json=minimal_patient()).json()["id"]
    application_id = as_admin.post(
        "/applications", json={"patient_id": patient_id}
    ).json()["id"]

    record = as_admin.post(
        f"/applications/{application_id}/files/deidentified",
        files=[("file", ("clean.pdf", _pdf_bytes(), "application/pdf"))],
    ).json()

    submission.finalise_submission(application_id)

    filed = deid_dirs["pdf"] / patient_id / record["deidentified_file_name"]
    assert filed.is_file(), "the attached document is gone after submitting"

    listed = as_admin.get(f"/applications/{application_id}/files").json()
    assert pathlib.Path(listed[0]["de_identified_file_path"]).is_file()


def _pdf_bytes() -> bytes:
    import io

    document = fitz.open()
    document.new_page().insert_text(fitz.Point(200, 400), "already redacted")
    buffer = io.BytesIO()
    document.save(buffer)
    document.close()
    return buffer.getvalue()
