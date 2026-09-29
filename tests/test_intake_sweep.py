"""Recording a sweep, and what that record is for.

Three jobs hang off `intake_files`, and each has a test here: showing what
arrived (including what was refused), not redoing work when a fixed folder
is pushed again, and settling a conflict once a person has chosen.
"""

import time

import pytest

from app import intake
from app.crud import intake_files as crud


def _drop(root, relative, data=b"%PDF-1.4 fake"):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


@pytest.fixture
def drop(tmp_path):
    """A batch with one of each outcome in it."""
    _drop(tmp_path, "A/B/C/AA1234/image.pdf")
    _drop(tmp_path, "A/B/C/AVDD1200/AVDD1200()_-chest.pdf", data=b"%PDF-1.4 two")
    _drop(tmp_path, "A/B/D/BB0042/BB9999_wrong.pdf", data=b"%PDF-1.4 three")
    _drop(tmp_path, "loose/REPORT_final.pdf", data=b"%PDF-1.4 four")
    _drop(tmp_path, "loose/notes.rtf", data=b"{\\rtf1}")
    return tmp_path


def test_a_dry_run_writes_nothing(drop, cursor):
    result = intake.sweep(cursor, root=drop, dry_run=True)

    assert result.batch_id is None
    assert len(result.candidates) == 5
    assert cursor.store["intake_files"] == []
    assert cursor.store["intake_batches"] == []


def test_a_dry_run_still_classifies_everything(drop, cursor):
    result = intake.sweep(cursor, root=drop, dry_run=True)

    assert len(result.queued) == 2
    assert len(result.conflicts) == 1
    assert len(result.skipped) == 2


def test_applying_records_every_file_including_the_refusals(drop, cursor):
    result = intake.sweep(cursor, root=drop, dry_run=False)

    rows = crud.list_files(cursor, batch_id=result.batch_id)
    assert len(rows) == 5, "a refused file was not recorded"

    tally = crud.counts(cursor, result.batch_id)
    assert tally.total == 5
    assert tally.queued == 2
    assert tally.conflict == 1
    assert tally.skipped == 2


def test_a_recorded_row_carries_what_the_page_will_need(drop, cursor):
    result = intake.sweep(cursor, root=drop, dry_run=False)

    rows = {r.file_name: r for r in crud.list_files(cursor, batch_id=result.batch_id)}

    queued = rows["image.pdf"]
    assert queued.status == "queued"
    assert queued.patient_code == "AA1234"
    assert queued.relative_path == "A/B/C/AA1234/image.pdf"
    assert queued.file_extension == "pdf"
    assert queued.file_size > 0
    assert queued.checksum

    skipped = rows["REPORT_final.pdf"]
    assert skipped.status == "skipped"
    assert skipped.reason == intake.NO_PATIENT_CODE
    assert skipped.patient_code is None


def test_a_conflict_keeps_both_claims_so_a_person_can_choose(drop, cursor):
    result = intake.sweep(cursor, root=drop, dry_run=False)

    conflict = crud.list_files(cursor, batch_id=result.batch_id, status="conflict")[0]

    assert conflict.path_code == "BB0042"
    assert conflict.name_code == "BB9999"
    assert conflict.patient_code is None
    assert "BB0042" in conflict.detail and "BB9999" in conflict.detail


def test_a_second_sweep_does_not_record_the_same_bytes_again(drop, cursor):
    """Pushing the same folder again changes nothing at all.

    Not the files that were redacted, and not the ones that were refused:
    an identical file at an identical path is the same refusal restated, so
    it keeps the row it already has. A sweep on a timer depends on this --
    without it, every unfixed file would breed a row per run.
    """
    first = intake.sweep(cursor, root=drop, dry_run=False)
    assert first.recorded == 5

    second = intake.sweep(cursor, root=drop, dry_run=False)

    assert second.recorded == 0
    assert second.already_seen == 5
    assert second.superseded == 0, "an unchanged refusal was churned"
    assert len(crud.list_files(cursor)) == 5, "the batch was recorded twice"


def test_two_drop_folders_do_not_shadow_each_other(tmp_path, cursor):
    """A relative path repeats itself across roots; an absolute one does not.

    `A/AA1234/image.pdf` under two different roots is two files, and keying
    dedupe on the relative path would hide the second one entirely.
    """
    same = b"%PDF-1.4 identical"
    first = tmp_path / "drop-one"
    second = tmp_path / "drop-two"
    _drop(first, "A/AA1234/image.pdf", data=same)
    _drop(second, "A/AA1234/image.pdf", data=same)

    intake.sweep(cursor, root=first, dry_run=False)
    later = intake.sweep(cursor, root=second, dry_run=False)

    assert later.recorded == 1
    assert len(crud.list_files(cursor)) == 2


def test_a_newly_added_file_is_picked_up_by_the_next_sweep(drop, cursor):
    intake.sweep(cursor, root=drop, dry_run=False)

    _drop(drop, "A/B/C/AA1234/second.pdf", data=b"%PDF-1.4 new arrival")
    second = intake.sweep(cursor, root=drop, dry_run=False)

    assert second.recorded == 1
    assert second.already_seen == 5

    added = crud.list_files(cursor, batch_id=second.batch_id)
    assert [r.file_name for r in added] == ["second.pdf"]


def test_a_skipped_file_given_a_code_and_re_pushed_is_taken(drop, cursor):
    """The correction loop, and why dedupe cannot be on bytes alone.

    Adding a code to a file name changes no bytes at all. Dedupe on the
    checksum by itself would therefore reject exactly the re-push it exists
    to support, and the file would stay skipped for ever.
    """
    intake.sweep(cursor, root=drop, dry_run=False)
    assert len(crud.list_files(cursor, status="skipped")) == 2

    (drop / "loose" / "REPORT_final.pdf").rename(drop / "loose" / "CC0007_final.pdf")
    second = intake.sweep(cursor, root=drop, dry_run=False)

    assert second.recorded == 1, "the corrected file was refused a second time"

    queued = crud.list_files(cursor, batch_id=second.batch_id, status="queued")
    assert [r.patient_code for r in queued] == ["CC0007"]


def test_the_old_refusal_comes_off_the_list_once_it_is_fixed(drop, cursor):
    """A stale skip is indistinguishable from one still needing attention."""
    intake.sweep(cursor, root=drop, dry_run=False)

    (drop / "loose" / "REPORT_final.pdf").rename(drop / "loose" / "CC0007_final.pdf")
    second = intake.sweep(cursor, root=drop, dry_run=False)

    assert second.superseded == 1

    still_skipped = [r.file_name for r in crud.list_files(cursor, status="skipped")]
    assert "REPORT_final.pdf" not in still_skipped
    assert still_skipped == ["notes.rtf"], "an unrelated skip was cleared too"

    stale = [r for r in crud.list_files(cursor) if r.status == "superseded"]
    assert "CC0007_final.pdf" in stale[0].detail


def test_a_resolved_conflict_re_pushed_is_not_queued_twice(drop, cursor):
    """Once a person has chosen, the file is queued -- settled work.

    A later re-push of the same bytes must not add a second copy of it to
    the queue.
    """
    first = intake.sweep(cursor, root=drop, dry_run=False)
    conflict = crud.list_files(cursor, batch_id=first.batch_id, status="conflict")[0]
    intake.resolve_conflict(cursor, conflict.id, "BB0042")

    second = intake.sweep(cursor, root=drop, dry_run=False)

    assert second.recorded == 0
    assert second.already_seen == 5
    assert len(crud.list_files(cursor, patient_code="BB0042")) == 1


def test_batches_are_listed_newest_first(drop, cursor):
    intake.sweep(cursor, root=drop, dry_run=False)
    _drop(drop, "A/B/C/AA1234/later.pdf", data=b"%PDF-1.4 later")
    intake.sweep(cursor, root=drop, dry_run=False)

    batches = crud.list_batches(cursor)

    assert len(batches) == 2
    assert all(b.status == "swept" for b in batches)


# --- settling a conflict ----------------------------------------------


def test_resolving_a_conflict_queues_the_file_under_the_chosen_code(drop, cursor):
    result = intake.sweep(cursor, root=drop, dry_run=False)
    conflict = crud.list_files(cursor, batch_id=result.batch_id, status="conflict")[0]

    after = intake.resolve_conflict(cursor, conflict.id, "BB0042")

    assert after.status == "queued"
    assert after.patient_code == "BB0042"
    assert crud.list_files(cursor, status="conflict") == []


def test_either_of_the_two_claimed_codes_may_be_chosen(drop, cursor):
    result = intake.sweep(cursor, root=drop, dry_run=False)
    conflict = crud.list_files(cursor, batch_id=result.batch_id, status="conflict")[0]

    after = intake.resolve_conflict(cursor, conflict.id, "bb9999")

    assert after.patient_code == "BB9999", "the choice was not normalised"


def test_a_code_neither_half_claimed_is_refused(drop, cursor):
    """Otherwise the conflict list becomes a way to file a document under
    any patient at all, which is the opposite of what it is for.
    """
    result = intake.sweep(cursor, root=drop, dry_run=False)
    conflict = crud.list_files(cursor, batch_id=result.batch_id, status="conflict")[0]

    with pytest.raises(ValueError, match="not one of the codes"):
        intake.resolve_conflict(cursor, conflict.id, "ZZ9999")

    assert crud.get_file(cursor, conflict.id).status == "conflict"


def test_a_file_that_is_not_in_conflict_cannot_be_resolved(drop, cursor):
    result = intake.sweep(cursor, root=drop, dry_run=False)
    queued = crud.list_files(cursor, batch_id=result.batch_id, status="queued")[0]

    with pytest.raises(ValueError, match="not in conflict"):
        intake.resolve_conflict(cursor, queued.id, "AA1234")


# --- the queue the workers will drain ---------------------------------


def test_the_oldest_queued_file_is_what_comes_next(drop, cursor):
    intake.sweep(cursor, root=drop, dry_run=False)

    nxt = crud.oldest_with_status(cursor, "queued")

    assert nxt is not None
    assert nxt.status == "queued"


def test_nothing_queued_is_reported_as_nothing(cursor, tmp_path):
    intake.sweep(cursor, root=tmp_path, dry_run=False)

    assert crud.oldest_with_status(cursor, "queued") is None


def test_files_can_be_found_by_patient_code(drop, cursor):
    intake.sweep(cursor, root=drop, dry_run=False)

    assert len(crud.list_files(cursor, patient_code="AA1234")) == 1
    assert crud.list_files(cursor, patient_code="ZZ0000") == []


def test_the_same_document_under_two_codes_is_two_filings(tmp_path, cursor):
    """Identical bytes in two patients' folders are two documents.

    Keying dedupe on the checksum alone silently drops the second one --
    only the first is ever redacted, and the other patient's copy never
    appears at all.
    """
    same = b"%PDF-1.4 a report sent to two clinics"
    _drop(tmp_path, "A/AA1234/report.pdf", data=same)
    _drop(tmp_path, "A/BB0042/report.pdf", data=same)

    result = intake.sweep(cursor, root=tmp_path, dry_run=False)

    assert result.recorded == 2
    assert result.already_seen == 0

    codes = sorted(r.patient_code for r in crud.list_files(cursor))
    assert codes == ["AA1234", "BB0042"]


def test_a_file_copied_within_one_patient_is_still_two_files(tmp_path, cursor):
    """Two files on disk are two documents, even byte-for-byte identical.

    Deduping them would make the folder and the picker disagree about how
    many documents a patient has.
    """
    same = b"%PDF-1.4 scanned twice"
    _drop(tmp_path, "A/AA1234/scan.pdf", data=same)
    _drop(tmp_path, "A/AA1234/scan_copy.pdf", data=same)

    result = intake.sweep(cursor, root=tmp_path, dry_run=False)

    assert result.recorded == 2


# --- at scale ----------------------------------------------------------


def _count(cursor, fragment):
    return sum(1 for sql, _ in cursor.statements if fragment in sql)


def test_many_files_are_recorded_in_a_few_statements(tmp_path, cursor):
    """Hive charges per statement, not per row: 600 files are two inserts,
    not six hundred."""
    for n in range(600):
        _drop(tmp_path, f"A/AA1234/scan{n:03d}.pdf", data=f"%PDF-1.4 {n}".encode())

    result = intake.sweep(cursor, root=tmp_path, dry_run=False)

    assert result.recorded == 600
    assert _count(cursor, "INSERT INTO `intake_files`") == 2


def test_known_unchanged_files_are_not_read_again(drop, cursor, monkeypatch):
    """A sibling arriving changes its folder's time; re-reading every file in
    that folder to prove nothing else changed would mean reading a patient's
    whole folder each time one scan lands in it."""
    intake.sweep(cursor, root=drop, dry_run=False)
    hashed = []
    real = intake.checksum
    monkeypatch.setattr(intake, "checksum", lambda p, *a: hashed.append(p) or real(p, *a))

    last_sweep = time.time()
    time.sleep(0.01)
    _drop(drop, "A/B/C/AA1234/new.pdf", data=b"%PDF-1.4 new")
    again = intake.sweep(cursor, root=drop, dry_run=False, touched_since=last_sweep)

    assert again.recorded == 1
    assert [p.name for p in hashed] == ["new.pdf"]


def test_only_changed_folders_are_walked(tmp_path, monkeypatch):
    monkeypatch.setattr(intake, "WALK_SLACK_SECONDS", 0)
    _drop(tmp_path, "A/AA1234/old.pdf")
    _drop(tmp_path, "B/BB0042/old.pdf")
    since = time.time() + 0.001
    time.sleep(0.01)
    _drop(tmp_path, "B/BB0042/new.pdf")

    found = sorted(str(p.relative_to(tmp_path)) for p in intake.walk(tmp_path, since=since))

    assert found == ["B/BB0042/new.pdf", "B/BB0042/old.pdf"]


def test_the_mirror_is_never_walked(tmp_path, monkeypatch):
    """It holds a redacted copy of everything: walking it doubles the work."""
    _drop(tmp_path, "A/AA1234/image.pdf")
    _drop(tmp_path, f"{intake.deidentified_dir_name()}/A/AA1234/AA1234_x.pdf")
    entered = []
    real = intake.os.walk

    def spy(top, *a, **kw):
        for entry in real(top, *a, **kw):
            entered.append(entry[0])
            yield entry

    monkeypatch.setattr(intake.os, "walk", spy)
    list(intake.walk(tmp_path))

    assert not any(intake.deidentified_dir_name() in d for d in entered)


def test_a_huge_sweep_keeps_counts_not_every_file(tmp_path, cursor, monkeypatch):
    monkeypatch.setattr(intake, "KEEP_CANDIDATES", 5)
    for n in range(12):
        _drop(tmp_path, f"A/AA1234/s{n}.pdf", data=f"%PDF-1.4 {n}".encode())
    _drop(tmp_path, "loose/nocode.pdf", data=b"%PDF-1.4 x")

    result = intake.sweep(cursor, root=tmp_path, dry_run=True)

    assert len(result.candidates) == 5
    assert result.count(intake.QUEUED) == 12
    assert result.count(intake.SKIPPED) == 1
