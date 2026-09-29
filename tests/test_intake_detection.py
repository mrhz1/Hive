"""Finding a patient code in a dropped folder.

This is the step with no safety net. There is no patient table to check a
candidate against -- patients do not exist until their files have been
redacted -- so a wrong answer here files somebody's scan under the wrong
person, before any human has looked at it. Hence the volume of cases.
"""

import time

import pytest

from app import intake


# --- in a file name ----------------------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ("AA1234.pdf", "AA1234"),
        ("AA1234_chest.pdf", "AA1234"),
        ("AA1234()_-something_in_the_name.pdf", "AA1234"),
        ("AA1234-chest-view.dcm", "AA1234"),
        ("AVDD001.dcm", "AVDD001"),
        ("AVDD1200 chest.docx", "AVDD1200"),
        ("aa1234_x.pdf", "AA1234"),
    ],
)
def test_a_code_is_read_off_the_name(name, expected):
    assert intake.code_in_name(name) == expected


@pytest.mark.parametrize(
    "name",
    [
        "image.dcm",
        "chest.pdf",
        "REPORT_final.pdf",
        "SCAN01_chest.pdf",
        "IMAGE1.dcm",
        "IM000001",
        "",
        ".pdf",
    ],
)
def test_a_name_with_no_code_claims_nothing(name):
    assert intake.code_in_name(name) is None


def test_a_longer_run_of_digits_is_not_truncated_to_a_code():
    """`AVDD12005` must not become `AVDD1200`.

    The boundary is what stops a code being carved out of a longer
    identifier -- which would silently file a document under a real
    patient who has nothing to do with it.
    """
    assert intake.code_in_name("AVDD12005_x.pdf") is None
    assert intake.code_in_name("AA12345.pdf") is None


def test_a_code_must_start_the_name():
    """A code buried mid-name is not a claim.

    `chest_AA1234.pdf` is somebody's description that happens to contain a
    code; taking it would make every incidental mention a filing decision.
    """
    assert intake.code_in_name("chest_AA1234.pdf") is None
    assert intake.code_in_name("scan-of-AA1234.dcm") is None


# --- in a path ---------------------------------------------------------


@pytest.mark.parametrize(
    "relative,expected",
    [
        ("A/B/C/AA1234/image.dcm", "AA1234"),
        ("AA1234/image.dcm", "AA1234"),
        ("A/B/C/AVDD1200/sub/folder/x.pdf", "AVDD1200"),
        ("A/B/C/image.dcm", None),
        ("image.dcm", None),
        ("REPORT/image.dcm", None),
    ],
)
def test_a_code_is_read_off_the_folders(relative, expected):
    assert intake.code_in_path(relative) == expected


def test_the_deepest_folder_code_wins():
    assert intake.code_in_path("AA1234/BB5678/x.pdf") == "BB5678"


def test_a_folder_code_must_be_the_whole_segment():
    """`AA1234-exported` is a folder somebody named, not a code."""
    assert intake.code_in_path("A/AA1234-exported/x.pdf") is None


# --- the two together -------------------------------------------------


def test_path_and_name_agreeing_gives_the_code():
    found = intake.detect("A/B/C/AA1234/AA1234_chest.pdf")

    assert found.code == "AA1234"
    assert not found.conflicted


def test_either_one_alone_is_enough():
    assert intake.detect("A/B/C/AA1234/image.dcm").code == "AA1234"
    assert intake.detect("A/B/C/loose/AA1234_image.dcm").code == "AA1234"


def test_a_disagreement_resolves_to_nothing_rather_than_to_a_guess():
    """Picking a side here is the worst available outcome.

    A file in AA1234's folder named for BB5678 means somebody dropped it in
    the wrong place. Either choice files a document under a patient it may
    not belong to, and redaction happens before anyone looks -- so the file
    waits for a person instead.
    """
    found = intake.detect("A/B/D/AA1234/BB5678_scan.pdf")

    assert found.conflicted
    assert found.code is None
    assert found.path_code == "AA1234"
    assert found.name_code == "BB5678"


# --- has the file finished arriving -----------------------------------


def test_a_file_still_being_written_is_not_settled(tmp_path):
    path = tmp_path / "big.dcm"
    path.write_bytes(b"half a study")

    assert not intake.is_settled(path, limit=30)


def test_a_file_that_has_sat_still_is_settled(tmp_path, monkeypatch):
    path = tmp_path / "done.dcm"
    path.write_bytes(b"a whole study")

    # Two minutes on. The file cannot be aged instead: its change time is
    # set by the filesystem and cannot be written, which is why it is used.
    now = time.time()
    monkeypatch.setattr(intake.time, "time", lambda: now + 120)

    assert intake.is_settled(path, limit=30)


def test_a_copied_file_that_kept_its_old_modified_time_is_not_settled(tmp_path):
    """`cp -p` and `rsync -t` carry the source's mtime over; ctime gives the
    copy away."""
    import os

    path = tmp_path / "copied.dcm"
    path.write_bytes(b"landed a moment ago")
    weeks_ago = time.time() - 30 * 86_400
    os.utime(path, (weeks_ago, weeks_ago))

    assert not intake.is_settled(path, limit=30)


def test_a_missing_file_is_never_settled(tmp_path):
    assert not intake.is_settled(tmp_path / "gone.pdf", limit=0)


def test_a_marker_says_the_push_has_finished(tmp_path):
    assert not intake.batch_is_marked_done(tmp_path)

    (tmp_path / intake.BATCH_MARKER).write_text("")

    assert intake.batch_is_marked_done(tmp_path)


# --- walking and classifying ------------------------------------------


def _drop(root, relative, data=b"%PDF-1.4 fake"):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_the_sweep_ignores_its_own_output(tmp_path):
    _drop(tmp_path, "A/AA1234/image.pdf")
    _drop(tmp_path, f"{intake.deidentified_dir_name()}/A/AA1234/AA1234_x.pdf")
    _drop(tmp_path, "_reports/last.json")
    (tmp_path / intake.BATCH_MARKER).write_text("")

    found = [str(p.relative_to(tmp_path)) for p in intake.walk(tmp_path)]

    assert found == ["A/AA1234/image.pdf"]


def test_a_missing_root_is_empty_rather_than_an_error(tmp_path):
    assert list(intake.walk(tmp_path / "nope")) == []


def test_each_outcome_lands_where_it_should(tmp_path):
    _drop(tmp_path, "A/B/C/AA1234/image.pdf")
    _drop(tmp_path, "A/B/D/BB0042/BB9999_wrong.pdf")
    _drop(tmp_path, "loose/REPORT_final.pdf")
    _drop(tmp_path, "loose/notes.rtf", data=b"{\\rtf1 not handled}")

    by_name = {c.name: c for c in intake.survey(tmp_path)}

    assert by_name["image.pdf"].status == intake.QUEUED
    assert by_name["image.pdf"].code == "AA1234"

    assert by_name["BB9999_wrong.pdf"].status == intake.CONFLICT
    assert by_name["BB9999_wrong.pdf"].reason == intake.CODE_CONFLICT

    assert by_name["REPORT_final.pdf"].status == intake.SKIPPED
    assert by_name["REPORT_final.pdf"].reason == intake.NO_PATIENT_CODE

    assert by_name["notes.rtf"].status == intake.SKIPPED
    assert by_name["notes.rtf"].reason == intake.UNSUPPORTED_FORMAT


def test_an_unsupported_format_is_reported_before_a_missing_code(tmp_path):
    """The format is the more useful complaint of the two.

    A .rtf in a patient folder is not going to be redacted whatever its
    code says, and telling somebody to add a code they already have wastes
    their time.
    """
    _drop(tmp_path, "A/AA1234/notes.rtf", data=b"{\\rtf1}")

    only = intake.survey(tmp_path)[0]

    assert only.reason == intake.UNSUPPORTED_FORMAT


def test_the_type_comes_from_the_bytes_when_the_name_lies(tmp_path):
    """A PACS export is routinely called IM000001, or worse, .txt."""
    _drop(tmp_path, "A/AA1234/notes.txt", data=b"%PDF-1.4 really a pdf")

    only = intake.survey(tmp_path)[0]

    assert only.extension == "pdf"
    assert only.status == intake.QUEUED


def test_the_redacted_copy_mirrors_the_tree_it_came_from(tmp_path):
    mirrored = intake.mirrored_dir("A/B/C/AA1234/image.dcm", tmp_path)

    assert mirrored == (
        tmp_path / intake.deidentified_dir_name() / "A" / "B" / "C" / "AA1234"
    )


def test_the_mirror_belongs_to_the_root_being_swept(tmp_path):
    """A sweep pointed elsewhere must not mirror into the configured root.

    Otherwise one batch's originals and its redacted copies end up in two
    unrelated folders.
    """
    assert intake.deidentified_root(tmp_path).parent == tmp_path


def test_checksums_identify_the_same_bytes_again(tmp_path):
    first = _drop(tmp_path, "A/AA1234/a.pdf", data=b"%PDF-1.4 same")
    second = _drop(tmp_path, "A/AA1234/b.pdf", data=b"%PDF-1.4 same")
    other = _drop(tmp_path, "A/AA1234/c.pdf", data=b"%PDF-1.4 different")

    assert intake.checksum(first) == intake.checksum(second)
    assert intake.checksum(first) != intake.checksum(other)


def test_an_unreadable_file_checksums_to_nothing_rather_than_raising(tmp_path):
    assert intake.checksum(tmp_path / "missing.pdf") == ""


def test_the_sweep_never_takes_the_submitted_folder(tmp_path, monkeypatch):
    """Nested inside the drop folder by configuration, it is still not intake.

    Otherwise every submitted document -- original and redacted copy alike --
    comes round again as a new arrival.
    """
    monkeypatch.setenv("SUBMITTED_DIR", str(tmp_path / "out"))
    _drop(tmp_path, "A/AA1234/image.pdf")
    _drop(tmp_path, "out/AA1234/original/old.pdf")
    _drop(tmp_path, "out/AA1234/de_identified/AA1234_x.pdf")

    found = [str(p.relative_to(tmp_path)) for p in intake.walk(tmp_path)]

    assert found == ["A/AA1234/image.pdf"]
