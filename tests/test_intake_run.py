"""Starting de-identification by itself once a push has landed.

The OCR pipeline is stubbed -- it has its own tests. What is under test is
the decision: nothing while a copy is still going, everything once it has
finished, and never two runs at once.
"""

import os
import threading
import time

import pytest

from app import intake, intake_run, intake_worker
from app.crud import intake_files as crud


def _drop(root, relative, data=b"%PDF-1.4 fake", age=None):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if age is not None:
        then = time.time() - age
        os.utime(path, (then, then))
    return path


@pytest.fixture
def root(tmp_path, patched_hive, monkeypatch):
    drop = tmp_path / "incoming_data"
    drop.mkdir()
    monkeypatch.setenv("INTAKE_DIR", str(drop))
    monkeypatch.setenv("INTAKE_SETTLE_SECONDS", "30")
    return drop


@pytest.fixture
def pipeline(monkeypatch):
    def fake(sources, output_dir, env=None, timeout=None):
        output_dir.mkdir(parents=True, exist_ok=True)
        out = {}
        for source in sources:
            produced = output_dir / f"{source.stem}_deid{source.suffix}"
            produced.write_bytes(b"%PDF-1.4 redacted")
            out[str(source)] = produced
        return out

    monkeypatch.setattr(intake_worker.deid, "run_pipeline_many", fake)
    monkeypatch.setattr(intake_worker, "embed_metadata", lambda *a, **kw: None)


def _backdate_everything(root, seconds=120):
    """Make the whole tree look long-settled -- mtime *and* ctime.

    ctime cannot be set directly, which is the point of using it; so the
    quiet window is shortened instead of the files being aged.
    """
    for path in root.rglob("*"):
        if path.is_file():
            then = time.time() - seconds
            os.utime(path, (then, then))


# --- deciding when ----------------------------------------------------


def test_an_empty_folder_is_idle(root):
    assert intake_run.push_state(root) == intake_run.IDLE


def test_a_folder_still_changing_is_left_alone(root, cursor, pipeline):
    _drop(root, "A/AA1234/image.pdf")

    result = intake_run.run_once(root)

    assert result.outcome == intake_run.ARRIVING
    assert crud.list_files(cursor) == [], "a half-copied push was swept"


def test_a_quiet_folder_is_swept_and_redacted(root, cursor, pipeline):
    _drop(root, "A/AA1234/image.pdf")
    _drop(root, "A/AA1234/second.pdf", data=b"%PDF-1.4 two")

    result = intake_run.run_once(root, quiet_seconds=0)

    assert result.outcome == intake_run.RAN
    assert result.swept == 2
    assert result.redacted == 2
    assert crud.counts(cursor).done == 2
    assert (root / intake.deidentified_dir_name() / "A" / "AA1234").is_dir()


def test_a_marker_starts_it_without_waiting(root, cursor, pipeline):
    """The sender saying "done" beats any amount of waiting.

    The files were written this instant and the quiet window is long, so
    only the marker can explain a run.
    """
    _drop(root, "A/AA1234/image.pdf")
    (root / "A" / intake.BATCH_MARKER).write_text("")

    result = intake_run.run_once(root)

    assert result.outcome == intake_run.RAN
    assert result.redacted == 1, "the files were swept but not redacted"


def test_a_spent_marker_is_removed(root, cursor, pipeline):
    """Left in place, the next push into the same folder would be taken as
    finished the moment its first file appeared."""
    _drop(root, "A/AA1234/image.pdf")
    marker = root / "A" / intake.BATCH_MARKER
    marker.write_text("")

    intake_run.run_once(root)

    assert not marker.exists()


def test_a_copy_that_kept_the_old_modified_time_still_counts_as_arriving(root):
    """`cp -p` and `rsync -t` carry the source's mtime over.

    A file copied a moment ago can claim to be days old; the change time,
    which no copy tool can set, gives it away.
    """
    _drop(root, "A/AA1234/image.pdf", age=86_400)

    assert intake_run.push_state(root) == intake_run.ARRIVING


def test_hidden_files_are_not_documents(root, cursor, pipeline):
    """rsync's in-flight `.image.pdf.Xy12` and Finder's .DS_Store."""
    _drop(root, "A/AA1234/image.pdf")
    _drop(root, "A/AA1234/.image2.pdf.Xy12Ab")
    _drop(root, ".DS_Store", data=b"junk")

    result = intake_run.run_once(root, quiet_seconds=0)

    assert result.swept == 1
    assert result.skipped == 0, "a temp file was reported as skipped"


# --- never twice at once ----------------------------------------------


def test_a_second_run_backs_off_while_the_first_is_working(root):
    with intake_run.exclusive(root) as first:
        assert first is True
        result = intake_run.run_once(root, quiet_seconds=0)

    assert result.outcome == intake_run.BUSY


def test_the_lock_is_released_when_a_run_ends(root, cursor, pipeline):
    intake_run.run_once(root, quiet_seconds=0)

    with intake_run.exclusive(root) as mine:
        assert mine is True


def test_the_lock_is_released_even_when_a_run_fails(root, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("hive went away")

    monkeypatch.setattr(intake_run, "push_state", boom)

    with pytest.raises(RuntimeError):
        intake_run.run_once(root)

    with intake_run.exclusive(root) as mine:
        assert mine is True, "a failed run left the lock held"


# --- leftovers and repeats --------------------------------------------


def test_a_second_run_over_the_same_folder_does_nothing(root, cursor, pipeline):
    _drop(root, "A/AA1234/image.pdf")
    intake_run.run_once(root, quiet_seconds=0)

    again = intake_run.run_once(root, quiet_seconds=0)

    assert again.swept == 0
    assert again.redacted == 0
    assert crud.counts(cursor).done == 1


def test_a_queue_left_by_an_interrupted_run_is_finished(root, cursor, pipeline):
    """A run stopped part-way leaves rows queued; the next one drains them
    even though nothing new has arrived."""
    _drop(root, "A/AA1234/image.pdf")
    intake.sweep(cursor, root=root, dry_run=False)
    for path in root.rglob("*.pdf"):
        path.unlink()  # the folder is now empty; only the queue remains
    (root / "A" / "AA1234").rmdir()

    # Put the file back where the row expects it, so it can be redacted.
    _drop(root, "A/AA1234/image.pdf")
    monkey_state = intake_run.push_state
    try:
        intake_run.push_state = lambda *a, **kw: intake_run.IDLE
        result = intake_run.run_once(root)
    finally:
        intake_run.push_state = monkey_state

    assert result.outcome == intake_run.RAN
    assert result.redacted == 1


def test_an_idle_folder_with_an_empty_queue_says_so(root, cursor):
    result = intake_run.run_once(root)

    assert result.outcome == intake_run.IDLE


# --- watching ---------------------------------------------------------


def test_watching_runs_until_told_to_stop(root, cursor, pipeline):
    _drop(root, "A/AA1234/image.pdf")
    stop = threading.Event()

    thread = threading.Thread(
        target=intake_run.watch,
        kwargs={"root": root, "every_seconds": 0.05, "quiet_seconds": 0, "stop": stop},
    )
    thread.start()
    deadline = time.time() + 5
    while time.time() < deadline and crud.counts(cursor).done == 0:
        time.sleep(0.05)
    stop.set()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert crud.counts(cursor).done == 1


# --- an unchanged folder is left alone ---------------------------------


def test_an_unchanged_folder_is_not_swept_again(root, cursor, pipeline):
    """"Quiet" is not the same as "new": last week's push is quiet too.

    Re-sweeping it every minute made a fresh empty batch and a database
    round-trip per file, each time, to find nothing.
    """
    _drop(root, "A/AA1234/image.pdf")
    first = intake_run.run_once(root, quiet_seconds=0)
    assert first.swept == 1

    for _ in range(3):
        again = intake_run.run_once(root, quiet_seconds=0)
        assert again.outcome == intake_run.IDLE

    assert len(crud.list_batches(cursor)) == 1, "an empty batch was made"


def test_a_new_file_after_a_sweep_is_picked_up(root, cursor, pipeline):
    _drop(root, "A/AA1234/image.pdf")
    intake_run.run_once(root, quiet_seconds=0)

    time.sleep(0.01)
    _drop(root, "A/AA1234/later.pdf", data=b"%PDF-1.4 later")
    again = intake_run.run_once(root, quiet_seconds=0)

    assert again.outcome == intake_run.RAN
    assert again.swept == 1
    assert crud.counts(cursor).done == 2


def test_a_resolved_conflict_is_redacted_without_the_folder_changing(
    root, cursor, pipeline
):
    """Choosing a code changes the queue, not the folder -- the watcher
    must still pick it up."""
    _drop(root, "A/BB0042/BB9999_wrong.pdf")
    intake_run.run_once(root, quiet_seconds=0)
    conflict = crud.list_files(cursor, status="conflict")[0]

    intake.resolve_conflict(cursor, conflict.id, "BB0042")
    again = intake_run.run_once(root, quiet_seconds=0)

    assert again.redacted == 1
    assert crud.get_file(cursor, conflict.id).status == "done"


def test_a_sweep_that_finds_nothing_new_makes_no_batch(root, cursor):
    _drop(root, "A/AA1234/image.pdf")
    intake.sweep(cursor, root=root, dry_run=False)

    again = intake.sweep(cursor, root=root, dry_run=False)

    assert again.batch_id is None
    assert len(crud.list_batches(cursor)) == 1


def test_a_sweep_asks_the_database_once_not_once_per_file(root, cursor, monkeypatch):
    """At about a second a query, per-file lookups turned a thousand-file
    folder into a quarter of an hour of checking."""
    for n in range(20):
        _drop(root, f"A/AA1234/scan{n}.pdf", data=f"%PDF-1.4 {n}".encode())
    intake.sweep(cursor, root=root, dry_run=False)

    lookups = []
    real = cursor.execute

    def counting(sql, params=()):
        if "FROM `intake_files`" in sql and "SELECT" in sql:
            lookups.append(sql)
        return real(sql, params)

    monkeypatch.setattr(cursor, "execute", counting)
    intake.sweep(cursor, root=root, dry_run=False)

    assert len(lookups) == 1, f"{len(lookups)} lookups for 20 known files"


# --- recovering from an interrupted run --------------------------------


def test_a_file_left_mid_redaction_by_a_stopped_run_is_redone(root, cursor, pipeline):
    """Ctrl-C, a restart, a killed Job: the row stays `processing`, and
    workers only take `queued` -- so without this it is stuck for ever."""
    _drop(root, "A/AA1234/image.pdf")
    intake.sweep(cursor, root=root, dry_run=False)
    stuck = crud.list_files(cursor, status="queued")[0]
    crud.update_file(cursor, stuck.id, intake_worker.IntakeFileUpdate(status="processing"))

    result = intake_run.run_once(root, quiet_seconds=0)

    assert result.redacted == 1
    assert crud.get_file(cursor, stuck.id).status == "done"


def test_a_done_file_whose_copy_was_deleted_is_redone(root, cursor, pipeline):
    """Clearing the mirror must not leave rows claiming files that are gone."""
    _drop(root, "A/AA1234/image.pdf")
    intake_run.run_once(root, quiet_seconds=0)
    record = crud.list_files(cursor, status="done")[0]

    import shutil

    shutil.rmtree(root / intake.deidentified_dir_name())
    result = intake_run.run_once(root, quiet_seconds=0)

    assert result.redacted == 1
    after = crud.get_file(cursor, record.id)
    assert after.status == "done"
    assert (root / intake.deidentified_dir_name()).is_dir()
    assert os.path.isfile(after.output_path)


def test_a_file_being_redacted_right_now_is_not_touched(root, cursor, pipeline):
    """Recovery only happens under the lock; a run that cannot get the lock
    must leave another run's `processing` rows alone."""
    _drop(root, "A/AA1234/image.pdf")
    intake.sweep(cursor, root=root, dry_run=False)
    busy = crud.list_files(cursor, status="queued")[0]
    crud.update_file(cursor, busy.id, intake_worker.IntakeFileUpdate(status="processing"))

    with intake_run.exclusive(root):
        result = intake_run.run_once(root, quiet_seconds=0)

    assert result.outcome == intake_run.BUSY
    assert crud.get_file(cursor, busy.id).status == "processing"


def test_submitted_files_are_not_redone_for_having_moved(root, cursor, pipeline):
    """Their copies left the mirror on purpose."""
    _drop(root, "A/AA1234/image.pdf")
    intake_run.run_once(root, quiet_seconds=0)
    record = crud.list_files(cursor, status="done")[0]
    crud.update_file(cursor, record.id, intake_worker.IntakeFileUpdate(status="submitted"))
    os.remove(record.output_path)

    intake_run.run_once(root, quiet_seconds=0)

    assert crud.get_file(cursor, record.id).status == "submitted"


# --- trying a failed file again ----------------------------------------


def _fail_it(cursor, root):
    _drop(root, "A/AA1234/image.pdf")
    intake_run.run_once(root, quiet_seconds=0)
    record = crud.list_files(cursor, status="done")[0]
    crud.update_file(
        cursor, record.id,
        intake_worker.IntakeFileUpdate(status="failed", detail="killed by SIGKILL"),
    )
    return record


def test_pushing_a_failed_file_again_retries_it(root, cursor, pipeline):
    """Same bytes, same place -- but put there again, which is a request."""
    record = _fail_it(cursor, root)

    time.sleep(0.01)
    _drop(root, "A/AA1234/image.pdf")  # pasted again, identical
    result = intake_run.run_once(root, quiet_seconds=0)

    assert result.redacted == 1
    assert crud.get_file(cursor, record.id).status == "done"
    assert len(crud.list_files(cursor)) == 1, "a duplicate row was made"


def test_a_failed_file_left_alone_is_not_retried_for_ever(root, cursor, pipeline):
    """Another file arriving must not re-run an unrelated failure."""
    record = _fail_it(cursor, root)

    time.sleep(0.01)
    _drop(root, "A/AA1234/other.pdf", data=b"%PDF-1.4 other")
    intake_run.run_once(root, quiet_seconds=0)

    assert crud.get_file(cursor, record.id).status == "failed"


def test_a_corrected_file_at_the_same_place_replaces_the_failure(
    root, cursor, pipeline
):
    """Different bytes where a failure was: the old failure describes a file
    that no longer exists, and must leave the Failed list."""
    record = _fail_it(cursor, root)

    time.sleep(0.01)
    _drop(root, "A/AA1234/image.pdf", data=b"%PDF-1.4 a fixed version")
    intake_run.run_once(root, quiet_seconds=0)

    assert crud.get_file(cursor, record.id).status == "superseded"
    assert crud.list_files(cursor, status="failed") == []
    assert crud.counts(cursor).done == 1


def test_a_failed_file_can_be_retried_by_hand(as_admin, root, cursor, pipeline):
    record = _fail_it(cursor, root)

    response = as_admin.post(f"/intake/files/{record.id}/retry")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "queued"

    result = intake_run.run_once(root, quiet_seconds=0)
    assert result.redacted == 1


def test_only_a_failed_file_can_be_retried(as_admin, root, cursor, pipeline):
    _drop(root, "A/AA1234/image.pdf")
    intake_run.run_once(root, quiet_seconds=0)
    done = crud.list_files(cursor, status="done")[0]

    response = as_admin.post(f"/intake/files/{done.id}/retry")

    assert response.status_code == 422
    assert "has not failed" in response.text


def test_retrying_a_file_that_is_gone_says_so(as_admin, root, cursor, pipeline):
    record = _fail_it(cursor, root)
    os.remove(record.source_path)

    response = as_admin.post(f"/intake/files/{record.id}/retry")

    assert response.status_code == 422
    assert "no longer at" in response.text


def test_retrying_needs_update_permission(client, root, cursor, pipeline):
    record = _fail_it(cursor, root)
    client.headers.update({"REMOTE-USER": "viewer"})

    assert client.post(f"/intake/files/{record.id}/retry").status_code == 403
