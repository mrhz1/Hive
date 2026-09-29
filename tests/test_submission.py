import pathlib

import fitz
import pytest

from app import storage, submission
from conftest import minimal_patient


@pytest.fixture
def deid_dirs(tmp_path, monkeypatch):
    """The submitted root: `<root>/<CODE>/{original,de_identified}/`."""
    root = tmp_path / "submitted"
    monkeypatch.setenv("SUBMITTED_DIR", str(root))
    return root


def redacted_dir(root, code):
    return root / code / "de_identified"


def original_dir(root, code):
    return root / code / "original"


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

    final = redacted_dir(deid_dirs, patient_id) / staged.name
    assert final.is_file(), "output was not moved to the configured location"
    assert not staged.exists(), "the staging copy was left behind"

    document = fitz.open(str(final))
    assert document.page_count == 3
    for page in document:
        words = page.get_text("words")
        stamps = [w for w in words if w[4] == patient_id]
        assert len(stamps) == 1, f"page {page.number} is not stamped"
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
    assert after["de_identified_file_path"] == str(redacted_dir(deid_dirs, patient_id) / staged.name)


def test_dicom_goes_to_the_dicom_directory_and_is_not_stamped(
    as_admin, storage_root, deid_dirs
):
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

    final = redacted_dir(deid_dirs, patient_id) / staged.name
    assert final.is_file()
    assert final.read_bytes() == b"redacted bytes", "a DICOM was rewritten"


def test_files_that_are_not_done_are_left_alone(as_admin, storage_root, deid_dirs):
    patient_id, application_id, record = _submitted_application(as_admin, storage_root)
    staged = _stage_output(record, storage_root)

    as_admin.put(
        f"/files/{record['id']}",
        json={"deid_status": "processing", "de_identified_file_path": str(staged)},
    )

    submission.finalise_submission(application_id)

    assert staged.is_file()
    assert not (redacted_dir(deid_dirs, patient_id) / staged.name).exists()


def test_a_missing_staged_file_does_not_raise(as_admin, storage_root, deid_dirs):
    _, application_id, record = _submitted_application(as_admin, storage_root)
    original = pathlib.Path(record["file_path"])
    missing = original.parent / "deidentified" / "not-there_deid.pdf"

    as_admin.put(
        f"/files/{record['id']}",
        json={"deid_status": "done", "de_identified_file_path": str(missing)},
    )

    submission.finalise_submission(application_id)


def test_submitting_through_the_api_triggers_it(as_admin, storage_root, deid_dirs):
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
    assert (redacted_dir(deid_dirs, patient_id) / staged.name).is_file()


def test_an_extensionless_dicom_is_filed_with_the_dicoms(
    as_admin, storage_root, deid_dirs
):
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

    assert (redacted_dir(deid_dirs, patient_id) / staged.name).is_file()


def test_re_saving_an_already_submitted_application_does_not_refile(
    as_admin, storage_root, deid_dirs
):
    patient_id, application_id, record = _submitted_application(as_admin, storage_root)
    staged = _stage_output(record, storage_root)
    as_admin.put(
        f"/files/{record['id']}",
        json={"deid_status": "done", "de_identified_file_path": str(staged)},
    )

    as_admin.put(f"/applications/{application_id}", json={"status": "submitted"})
    as_admin.put(f"/applications/{application_id}", json={"status": "submitted"})

    final = redacted_dir(deid_dirs, patient_id) / staged.name
    document = fitz.open(str(final))
    stamps = [w for w in document[0].get_text("words") if w[4] == patient_id]
    document.close()

    assert len(stamps) == 1, "the id was stamped more than once"


def test_submitting_files_the_original_beside_its_redacted_copy(
    as_admin, storage_root, deid_dirs
):
    patient_id, application_id, record = _submitted_application(
        as_admin, storage_root
    )
    original = pathlib.Path(record["file_path"])
    staged = _stage_output(record, storage_root)

    as_admin.put(
        f"/files/{record['id']}",
        json={"deid_status": "done", "de_identified_file_path": str(staged)},
    )

    submission.finalise_submission(application_id)

    moved = original_dir(deid_dirs, patient_id) / original.name
    assert moved.is_file(), "the original was not filed"
    assert not original.exists(), "the original was copied, not moved"
    assert (redacted_dir(deid_dirs, patient_id) / staged.name).is_file()

    after = as_admin.get(f"/files/{record['id']}").json()
    assert after["file_path"] == str(moved)


def test_both_copies_are_reachable_from_the_one_row(
    as_admin, storage_root, deid_dirs
):
    """The pairing is the row, not the file names.

    A redacted copy is named for its own run, so the two names do not
    match on disk. What links them is the row holding both paths.
    """
    _, application_id, record = _submitted_application(as_admin, storage_root)
    staged = _stage_output(record, storage_root)

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

    after = as_admin.get(f"/files/{record['id']}").json()
    assert pathlib.Path(after["file_path"]).is_file()
    assert pathlib.Path(after["de_identified_file_path"]).is_file()

    identified = as_admin.get(f"/files/{record['id']}/content")
    redacted = as_admin.get(f"/files/{record['id']}/content?deidentified=true")
    assert identified.status_code == 200
    assert redacted.status_code == 200
    assert identified.content != redacted.content


def test_turning_the_flag_off_discards_the_original(
    as_admin, storage_root, deid_dirs, monkeypatch
):
    monkeypatch.setenv("DEID_KEEP_ORIGINAL", "false")

    patient_id, application_id, record = _submitted_application(
        as_admin, storage_root
    )
    original = pathlib.Path(record["file_path"])
    staged = _stage_output(record, storage_root)

    as_admin.put(
        f"/files/{record['id']}",
        json={"deid_status": "done", "de_identified_file_path": str(staged)},
    )

    submission.finalise_submission(application_id)

    assert not original.exists(), "the identified copy is still on disk"
    assert (redacted_dir(deid_dirs, patient_id) / staged.name).is_file()


def test_an_original_without_a_redacted_copy_is_kept(
    as_admin, storage_root, deid_dirs
):
    _, application_id, record = _submitted_application(as_admin, storage_root)
    original = pathlib.Path(record["file_path"])
    staged = _stage_output(record, storage_root)

    as_admin.put(
        f"/files/{record['id']}",
        json={"deid_status": "processing", "de_identified_file_path": str(staged)},
    )

    submission.finalise_submission(application_id)

    assert original.is_file()



def test_discarding_the_original_clears_out_the_upload_folder(
    as_admin, storage_root, deid_dirs, monkeypatch
):
    monkeypatch.setenv("DEID_KEEP_ORIGINAL", "false")

    _, application_id, record = _submitted_application(as_admin, storage_root)
    original = pathlib.Path(record["file_path"])
    staged = _stage_output(record, storage_root)

    as_admin.put(
        f"/files/{record['id']}",
        json={"deid_status": "done", "de_identified_file_path": str(staged)},
    )

    submission.finalise_submission(application_id)

    assert not original.parent.exists(), "the upload folder was left behind"


def test_submitting_leaves_no_empty_folders_behind(
    as_admin, storage_root, deid_dirs
):
    """Both copies leave, so neither folder they came from should linger."""
    _, application_id, record = _submitted_application(as_admin, storage_root)
    original = pathlib.Path(record["file_path"])
    staged = _stage_output(record, storage_root)

    as_admin.put(
        f"/files/{record['id']}",
        json={"deid_status": "done", "de_identified_file_path": str(staged)},
    )

    submission.finalise_submission(application_id)

    assert not staged.parent.exists(), "the staging folder was left behind"
    assert not original.parent.exists(), "the upload folder was left behind"


def test_two_documents_with_one_name_do_not_overwrite_each_other(
    as_admin, storage_root, deid_dirs
):
    """`image.dcm` from two series is two documents, not one."""
    patient_id, application_id, first = _submitted_application(
        as_admin, storage_root, name="image.pdf"
    )
    second = as_admin.post(
        f"/applications/{application_id}/files",
        files=[("files", ("image.pdf", b"%PDF-1.4 other", "application/pdf"))],
    ).json()[0]

    for record in (first, second):
        staged = _stage_output(record, storage_root)
        # Same redacted name for both, as two runs could produce.
        clash = staged.parent / record["id"] / "AA_same_name.pdf"
        clash.parent.mkdir()
        staged.rename(clash)
        as_admin.put(
            f"/files/{record['id']}",
            json={"deid_status": "done", "de_identified_file_path": str(clash)},
        )

    submission.finalise_submission(application_id)

    redacted = sorted(p.name for p in redacted_dir(deid_dirs, patient_id).iterdir())
    assert redacted == ["AA_same_name.pdf", "AA_same_name_2.pdf"]


def test_submitting_takes_the_run_s_text_and_report_with_it(
    as_admin, storage_root, deid_dirs
):
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
    patient_id = as_admin.post("/patients", json=minimal_patient()).json()["id"]
    application_id = as_admin.post(
        "/applications", json={"patient_id": patient_id}
    ).json()["id"]

    record = as_admin.post(
        f"/applications/{application_id}/files/deidentified",
        files=[("file", ("clean.pdf", _pdf_bytes(), "application/pdf"))],
    ).json()

    submission.finalise_submission(application_id)

    filed = redacted_dir(deid_dirs, patient_id) / record["deidentified_file_name"]
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
