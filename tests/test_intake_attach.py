"""Picking redacted files from intake onto an application.

The code on the document is the only evidence of whose it is, so attaching
is where that evidence meets a patient record -- and where a click could
otherwise override it.
"""

import pathlib

import pytest

from app import intake
from app.crud import intake_files as crud
from app.schemas import IntakeFileUpdate
from conftest import minimal_patient


def _drop(root, relative, data=b"%PDF-1.4 fake"):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _redact(cursor, root, record):
    """What a worker leaves behind: a redacted twin in the mirror."""
    output_dir = intake.mirrored_dir(record.relative_path, root)
    output_dir.mkdir(parents=True, exist_ok=True)
    name = f"{record.patient_code}_20260924_{record.id[:16].replace('-', '0')}.pdf"
    output = output_dir / name
    output.write_bytes(b"%PDF-1.4 redacted")
    crud.update_file(
        cursor,
        record.id,
        IntakeFileUpdate(status="done", output_path=str(output), output_name=name),
    )


@pytest.fixture
def drop(tmp_path, monkeypatch, cursor):
    """Two patients' files, swept and redacted, under the configured root."""
    monkeypatch.setenv("INTAKE_DIR", str(tmp_path))

    _drop(tmp_path, "A/B/C/AA1234/image.pdf")
    _drop(tmp_path, "A/B/C/AA1234/sub/second.pdf", data=b"%PDF-1.4 two")
    _drop(tmp_path, "A/B/D/BB0042/scan.pdf", data=b"%PDF-1.4 three")
    _drop(tmp_path, "A/B/D/CC0007/queued.pdf", data=b"%PDF-1.4 four")

    intake.sweep(cursor, root=tmp_path, dry_run=False)
    for record in crud.list_files(cursor, status="queued"):
        if record.patient_code != "CC0007":
            _redact(cursor, tmp_path, record)
    return tmp_path


def _application(client, code):
    client.post("/patients", json=minimal_patient(id=code))
    return client.post("/applications", json={"patient_id": code}).json()["id"]


def _done(cursor, code):
    return [r for r in crud.list_files(cursor, status="done") if r.patient_code == code]


# --- choosing a code ---------------------------------------------------


def test_codes_with_redacted_files_are_offered(as_admin, drop):
    codes = {c["code"]: c for c in as_admin.get("/intake/codes").json()}

    assert set(codes) == {"AA1234", "BB0042"}, "a not-yet-redacted code was offered"
    assert codes["AA1234"]["files"] == 2
    assert codes["AA1234"]["folder"] == str(drop / "A/B/C/AA1234")


def test_a_code_says_whether_its_patient_exists(as_admin, drop):
    as_admin.post("/patients", json=minimal_patient(id="BB0042"))

    codes = {c["code"]: c for c in as_admin.get("/intake/codes").json()}

    assert codes["BB0042"]["patient_exists"] is True
    assert codes["AA1234"]["patient_exists"] is False


def test_a_patient_is_created_from_the_code_on_the_files(as_admin, drop):
    created = as_admin.post("/patients", json=minimal_patient(id="AA1234"))

    assert created.status_code == 201
    assert created.json()["id"] == "AA1234"


# --- attaching ---------------------------------------------------------


def test_attaching_puts_both_copies_on_one_row(as_admin, drop, cursor):
    application_id = _application(as_admin, "AA1234")
    picked = _done(cursor, "AA1234")

    response = as_admin.post(
        f"/applications/{application_id}/intake-files",
        json={"intake_file_ids": [r.id for r in picked]},
    )

    assert response.status_code == 201, response.text
    rows = response.json()
    assert len(rows) == 2

    row = next(r for r in rows if r["original_file_name"] == "image.pdf")
    assert row["file_path"] == str(drop / "A/B/C/AA1234/image.pdf")
    assert row["de_identified_file_path"].startswith(
        str(drop / intake.deidentified_dir_name())
    )
    assert row["deid_status"] == "done"
    assert row["is_deidentified"] is True
    assert row["deidentified_file_name"].startswith("AA1234_")


def test_both_copies_can_be_read_through_the_application(as_admin, drop, cursor):
    """The drop folder is a storage root now; without that, every read of an
    attached file is refused and logged as a traversal attempt."""
    application_id = _application(as_admin, "AA1234")
    picked = [r for r in _done(cursor, "AA1234") if r.file_name == "image.pdf"]
    row = as_admin.post(
        f"/applications/{application_id}/intake-files",
        json={"intake_file_ids": [picked[0].id]},
    ).json()[0]

    original = as_admin.get(f"/files/{row['id']}/content")
    redacted = as_admin.get(f"/files/{row['id']}/content?deidentified=true")

    assert original.status_code == 200
    assert redacted.status_code == 200
    assert original.content == b"%PDF-1.4 fake"
    assert redacted.content == b"%PDF-1.4 redacted"


def test_an_attached_file_is_claimed_and_no_longer_offered(as_admin, drop, cursor):
    application_id = _application(as_admin, "AA1234")
    picked = _done(cursor, "AA1234")

    as_admin.post(
        f"/applications/{application_id}/intake-files",
        json={"intake_file_ids": [r.id for r in picked]},
    )

    assert all(crud.get_file(cursor, r.id).status == "claimed" for r in picked)
    codes = [c["code"] for c in as_admin.get("/intake/codes").json()]
    assert "AA1234" not in codes


def test_a_file_cannot_be_attached_to_a_second_application(as_admin, drop, cursor):
    first = _application(as_admin, "AA1234")
    second = as_admin.post("/applications", json={"patient_id": "AA1234"}).json()["id"]
    picked = _done(cursor, "AA1234")[:1]

    as_admin.post(
        f"/applications/{first}/intake-files",
        json={"intake_file_ids": [picked[0].id]},
    )
    again = as_admin.post(
        f"/applications/{second}/intake-files",
        json={"intake_file_ids": [picked[0].id]},
    )

    assert again.status_code == 422
    assert "already attached" in again.text


def test_another_patient_s_file_is_refused(as_admin, drop, cursor):
    """A click must not override the code the document carries."""
    application_id = _application(as_admin, "AA1234")
    theirs = _done(cursor, "BB0042")

    response = as_admin.post(
        f"/applications/{application_id}/intake-files",
        json={"intake_file_ids": [theirs[0].id]},
    )

    assert response.status_code == 422
    assert "belongs to BB0042" in response.text
    assert crud.get_file(cursor, theirs[0].id).status == "done"


def test_a_file_not_yet_redacted_is_refused(as_admin, drop, cursor):
    application_id = _application(as_admin, "CC0007")
    waiting = [r for r in crud.list_files(cursor) if r.patient_code == "CC0007"]

    response = as_admin.post(
        f"/applications/{application_id}/intake-files",
        json={"intake_file_ids": [waiting[0].id]},
    )

    assert response.status_code == 422
    assert "has not been de-identified" in response.text


def test_one_bad_file_attaches_nothing(as_admin, drop, cursor):
    """A half-attached selection is harder to reason about than a refused one."""
    application_id = _application(as_admin, "AA1234")
    mine = _done(cursor, "AA1234")
    theirs = _done(cursor, "BB0042")

    response = as_admin.post(
        f"/applications/{application_id}/intake-files",
        json={"intake_file_ids": [mine[0].id, theirs[0].id]},
    )

    assert response.status_code == 422
    assert as_admin.get(f"/applications/{application_id}/files").json() == []
    assert crud.get_file(cursor, mine[0].id).status == "done"


def test_a_missing_redacted_copy_is_refused(as_admin, drop, cursor):
    application_id = _application(as_admin, "AA1234")
    record = _done(cursor, "AA1234")[0]
    pathlib.Path(record.output_path).unlink()

    response = as_admin.post(
        f"/applications/{application_id}/intake-files",
        json={"intake_file_ids": [record.id]},
    )

    assert response.status_code == 422
    assert "missing from disk" in response.text


def test_a_submitted_application_takes_no_new_files(as_admin, drop, cursor):
    application_id = _application(as_admin, "AA1234")
    as_admin.put(f"/applications/{application_id}", json={"status": "submitted"})

    response = as_admin.post(
        f"/applications/{application_id}/intake-files",
        json={"intake_file_ids": [_done(cursor, "AA1234")[0].id]},
    )

    assert response.status_code == 422


def test_an_empty_selection_is_refused(as_admin, drop):
    application_id = _application(as_admin, "AA1234")

    response = as_admin.post(
        f"/applications/{application_id}/intake-files", json={"intake_file_ids": []}
    )

    assert response.status_code == 422


# --- taking it back off -----------------------------------------------


def test_removing_an_attached_file_hands_it_back_and_keeps_both_copies(
    as_admin, drop, cursor
):
    """Taking a document off a draft means "not in this application".

    It does not mean "destroy the original". The file goes back to the
    pool, both copies intact, ready to be picked again.
    """
    application_id = _application(as_admin, "AA1234")
    record = _done(cursor, "AA1234")[0]
    row = as_admin.post(
        f"/applications/{application_id}/intake-files",
        json={"intake_file_ids": [record.id]},
    ).json()[0]

    assert as_admin.delete(f"/files/{row['id']}").status_code == 204

    assert pathlib.Path(record.source_path).is_file(), "the original was deleted"
    assert pathlib.Path(record.output_path).is_file(), "the redacted copy was deleted"

    back = crud.get_file(cursor, record.id)
    assert back.status == "done"
    assert back.claimed_by_file_id is None


def test_deleting_an_application_hands_its_intake_files_back(as_admin, drop, cursor):
    application_id = _application(as_admin, "AA1234")
    picked = _done(cursor, "AA1234")
    as_admin.post(
        f"/applications/{application_id}/intake-files",
        json={"intake_file_ids": [r.id for r in picked]},
    )

    as_admin.delete(
        f"/applications/{application_id}", params={"reason": "started again"}
    )

    for record in picked:
        assert crud.get_file(cursor, record.id).status == "done"
        assert pathlib.Path(record.source_path).is_file()
        assert pathlib.Path(record.output_path).is_file()


def test_attaching_needs_update_permission(client, drop, cursor):
    client.headers.update({"REMOTE-USER": "admin"})
    application_id = _application(client, "AA1234")

    client.headers.update({"REMOTE-USER": "viewer"})
    response = client.post(
        f"/applications/{application_id}/intake-files",
        json={"intake_file_ids": [_done(cursor, "AA1234")[0].id]},
    )

    assert response.status_code == 403


# --- submission --------------------------------------------------------


@pytest.fixture
def submitted_root(tmp_path, monkeypatch):
    root = tmp_path / "submitted"
    monkeypatch.setenv("SUBMITTED_DIR", str(root))
    return root


def _attach_all(client, cursor, code):
    application_id = _application(client, code)
    client.post(
        f"/applications/{application_id}/intake-files",
        json={"intake_file_ids": [r.id for r in _done(cursor, code)]},
    )
    return application_id


def test_submitting_files_both_copies_under_the_patient(
    as_admin, drop, cursor, submitted_root
):
    """`submitted/<CODE>/original/` and `submitted/<CODE>/de_identified/`."""
    application_id = _attach_all(as_admin, cursor, "AA1234")

    as_admin.put(f"/applications/{application_id}", json={"status": "submitted"})

    folder = submitted_root / "AA1234"
    originals = sorted(p.name for p in (folder / "original").iterdir())
    redacted = sorted(p.name for p in (folder / "de_identified").iterdir())

    assert originals == ["image.pdf", "second.pdf"]
    assert len(redacted) == 2
    assert all(name.startswith("AA1234_") for name in redacted)

    for row in as_admin.get(f"/applications/{application_id}/files").json():
        assert pathlib.Path(row["file_path"]).parent == folder / "original"
        assert pathlib.Path(row["de_identified_file_path"]).parent == folder / "de_identified"


def test_submitting_empties_the_drop_tree_it_came_from(
    as_admin, drop, cursor, submitted_root
):
    application_id = _attach_all(as_admin, cursor, "AA1234")
    as_admin.put(f"/applications/{application_id}", json={"status": "submitted"})

    assert not (drop / "A/B/C/AA1234").exists(), "the original folder lingered"
    mirror = drop / intake.deidentified_dir_name() / "A/B/C/AA1234"
    assert not mirror.exists(), "the redacted copy's folder lingered"

    # Another patient's files in the same tree are untouched.
    assert (drop / "A/B/D/BB0042/scan.pdf").is_file()


def test_the_run_s_text_and_report_do_not_survive_submission(
    as_admin, drop, cursor, submitted_root
):
    """The report is the one artifact that can hold identifiers in the clear."""
    record = _done(cursor, "AA1234")[0]
    output = pathlib.Path(record.output_path)
    report = output.with_name(output.stem + ".report.json")
    text = output.with_suffix(".txt")
    report.write_text('{"values": ["Jane Doe"]}')
    text.write_text("redacted text")

    application_id = _attach_all(as_admin, cursor, "AA1234")
    as_admin.put(f"/applications/{application_id}", json={"status": "submitted"})

    assert not report.exists()
    assert not text.exists()


def test_a_submitted_file_is_closed_not_handed_back(
    as_admin, drop, cursor, submitted_root
):
    """Its copies have left the drop tree; offering it again would offer
    files that are no longer where the row says."""
    application_id = _attach_all(as_admin, cursor, "AA1234")
    picked = [r.id for r in crud.list_files(cursor, status="claimed")]

    as_admin.put(f"/applications/{application_id}", json={"status": "submitted"})

    assert {crud.get_file(cursor, i).status for i in picked} == {"submitted"}
    assert "AA1234" not in [c["code"] for c in as_admin.get("/intake/codes").json()]


def test_re_pushing_a_submitted_folder_does_not_redact_it_again(
    as_admin, drop, cursor, submitted_root
):
    """The sender pushes the same folder back after it has gone through.

    The intake row still remembers where each file arrived, which is what
    makes this a duplicate rather than new work.
    """
    application_id = _attach_all(as_admin, cursor, "AA1234")
    as_admin.put(f"/applications/{application_id}", json={"status": "submitted"})

    _drop(drop, "A/B/C/AA1234/image.pdf")
    _drop(drop, "A/B/C/AA1234/sub/second.pdf", data=b"%PDF-1.4 two")
    again = intake.sweep(cursor, root=drop, dry_run=False)

    assert again.recorded == 0
    assert crud.list_files(cursor, status="queued") == [
        r for r in crud.list_files(cursor, status="queued") if r.patient_code == "CC0007"
    ]


def test_the_submitted_copies_can_still_be_read(as_admin, drop, cursor, submitted_root):
    application_id = _attach_all(as_admin, cursor, "AA1234")
    as_admin.put(f"/applications/{application_id}", json={"status": "submitted"})

    row = as_admin.get(f"/applications/{application_id}/files").json()[0]

    assert as_admin.get(f"/files/{row['id']}/content").status_code == 200
    assert (
        as_admin.get(f"/files/{row['id']}/content?deidentified=true").status_code == 200
    )
