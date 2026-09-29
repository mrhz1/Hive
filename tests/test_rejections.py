"""The rejection queue: what a reviewer turned down, across applications.

Rejections are the one state that needs working through by hand -- a file
whose redaction was not good enough needs a better copy attached, and the
application it belongs to cannot be submitted until that happens. These
cover the two listings the page reads and the replacement that clears a
file off it.
"""

import pathlib

import pytest

from app import storage
from conftest import minimal_patient


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


def _redacted_file(client, name="scan.pdf", patient_id=None):
    if patient_id is None:
        patient_id = client.post("/patients", json=minimal_patient()).json()["id"]
    application_id = client.post(
        "/applications", json={"patient_id": patient_id}
    ).json()["id"]
    record = client.post(
        f"/applications/{application_id}/files",
        files=[("files", (name, b"%PDF-1.4 identified", "application/pdf"))],
    ).json()[0]

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
    return patient_id, application_id, record


def _reject(client, file_id, note="faces still visible on page 2"):
    response = client.post(
        f"/files/{file_id}/review",
        json={"review_status": "rejected", "review_note": note},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_only_rejected_files_are_listed(as_admin, storage_root):
    _, _, rejected = _redacted_file(as_admin, name="bad.pdf")
    _, _, approved = _redacted_file(as_admin, name="good.pdf")
    _redacted_file(as_admin, name="untouched.pdf")

    _reject(as_admin, rejected["id"])
    as_admin.post(
        f"/files/{approved['id']}/review", json={"review_status": "approved"}
    )

    rows = as_admin.get("/files/rejected").json()

    assert [row["original_file_name"] for row in rows] == ["bad.pdf"]


def test_a_rejected_row_carries_what_the_page_needs(as_admin, storage_root):
    patient_id, application_id, record = _redacted_file(as_admin)
    _reject(as_admin, record["id"], note="illegible, rescan")

    row = as_admin.get("/files/rejected").json()[0]

    assert row["id"] == record["id"]
    assert row["patient_id"] == patient_id
    assert row["application_id"] == application_id
    assert row["review_note"] == "illegible, rescan"
    assert row["file_extension"] == "pdf"

    # Both copies are on disk, so the page may offer both downloads.
    assert row["has_original"] is True
    assert row["has_deidentified"] is True


def test_a_missing_original_is_reported_rather_than_assumed(
    as_admin, storage_root
):
    """DEID_KEEP_ORIGINAL is not retroactive.

    An application submitted before it was turned on has no identified copy
    left, and the page must not offer a download that cannot work.
    """
    _, _, record = _redacted_file(as_admin)
    _reject(as_admin, record["id"])

    pathlib.Path(record["file_path"]).unlink()

    row = as_admin.get("/files/rejected").json()[0]
    assert row["has_original"] is False
    assert row["has_deidentified"] is True


def test_the_listing_does_not_shadow_a_file_by_id(as_admin, storage_root):
    _, _, record = _redacted_file(as_admin)

    assert as_admin.get("/files/rejected").status_code == 200
    assert as_admin.get(f"/files/{record['id']}").json()["id"] == record["id"]


def test_rejected_applications_can_be_asked_for_on_their_own(
    as_admin, storage_root
):
    _, rejected_id, _ = _redacted_file(as_admin, name="a.pdf")
    _, draft_id, _ = _redacted_file(as_admin, name="b.pdf")

    as_admin.post(
        f"/applications/{rejected_id}/reject",
        json={"reason": "wrong patient throughout"},
    )

    rows = as_admin.get("/applications", params={"status": "rejected"}).json()

    assert [row["id"] for row in rows] == [rejected_id]
    assert rows[0]["status_reason"] == "wrong patient throughout"

    everything = as_admin.get("/applications").json()
    assert {row["id"] for row in everything} == {rejected_id, draft_id}


def test_replacing_the_redacted_copy_sends_the_file_back_for_review(
    as_admin, storage_root, deid_dirs
):
    """A verdict belongs to the bytes it was given.

    The replacement has not been reviewed, so it goes back to pending
    rather than inheriting the rejection -- which is also what takes it off
    the rejection queue.
    """
    patient_id, _, record = _redacted_file(as_admin)
    _reject(as_admin, record["id"], note="faces still visible")

    assert len(as_admin.get("/files/rejected").json()) == 1

    response = as_admin.post(
        "/files-library",
        data={"patient_id": patient_id, "replaces_file_id": record["id"]},
        files=[("file", ("fixed.pdf", b"%PDF-1.4 properly redacted", "application/pdf"))],
    )
    assert response.status_code == 201, response.text

    after = as_admin.get(f"/files/{record['id']}").json()
    assert after["review_status"] == "pending"
    assert after["review_note"] is None
    assert after["deid_status"] == "done"
    assert after["is_deidentified"] is True

    assert as_admin.get("/files/rejected").json() == []


def test_the_replaced_verdict_is_kept_in_the_audit_trail(
    as_admin, storage_root, deid_dirs
):
    """Clearing the note off the row must not lose why it was rejected."""
    patient_id, _, record = _redacted_file(as_admin)
    _reject(as_admin, record["id"], note="page 2 not redacted")

    as_admin.post(
        "/files-library",
        data={"patient_id": patient_id, "replaces_file_id": record["id"]},
        files=[("file", ("fixed.pdf", b"%PDF-1.4 fixed", "application/pdf"))],
    )

    entries = as_admin.get(
        "/logs",
        params={"entity_type": "deidentified_file", "entity_id": record["id"]},
    ).json()

    replacements = [entry for entry in entries if entry["action"] == "REPLACE"]
    assert replacements, "the replacement was not audited"

    old = replacements[0]["old_values"]
    assert old["review_status"] == "rejected"
    assert old["review_note"] == "page 2 not redacted"


def test_an_approved_file_replaced_also_goes_back_to_pending(
    as_admin, storage_root, deid_dirs
):
    patient_id, _, record = _redacted_file(as_admin)
    as_admin.post(f"/files/{record['id']}/review", json={"review_status": "approved"})

    as_admin.post(
        "/files-library",
        data={"patient_id": patient_id, "replaces_file_id": record["id"]},
        files=[("file", ("fixed.pdf", b"%PDF-1.4 fixed", "application/pdf"))],
    )

    after = as_admin.get(f"/files/{record['id']}").json()
    assert after["review_status"] == "pending", (
        "an approval carried over to bytes nobody has reviewed"
    )


def test_listing_rejections_needs_permission(client, storage_root):
    response = client.get("/files/rejected", headers={"REMOTE-USER": "nobody"})
    assert response.status_code in (401, 403)
