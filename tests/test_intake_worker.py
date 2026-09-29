"""Redacting a swept batch -- chunks, shards, a journal, a heartbeat.

The OCR pipeline is stubbed; it is a subprocess with its own tests. What is
under test is everything around it: a file is never claimed twice, a bad
document costs only itself, outcomes survive a killed worker, and the output
lands in the mirror under the patient code.
"""

import json
import os
import threading
from pathlib import Path

import pytest

from app import intake, intake_worker
from app.crud import intake_files as crud
from app.schemas import IntakeFileUpdate


def _drop(root, relative, data=b"%PDF-1.4 fake"):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


@pytest.fixture
def swept(tmp_path, cursor, patched_hive, monkeypatch):
    """A batch already swept, with three files queued."""
    monkeypatch.setenv("INTAKE_DIR", str(tmp_path))
    monkeypatch.setenv("INTAKE_SETTLE_SECONDS", "0")
    _drop(tmp_path, "A/B/C/AA1234/image.pdf")
    _drop(tmp_path, "A/B/C/AA1234/second.pdf", data=b"%PDF-1.4 two")
    _drop(tmp_path, "A/B/D/BB0042/BB0042_chest.pdf", data=b"%PDF-1.4 three")
    _drop(tmp_path, "loose/REPORT.pdf", data=b"%PDF-1.4 four")
    intake.sweep(cursor, root=tmp_path, dry_run=False)
    return tmp_path


class Pipeline:
    """Stand in for run_pipeline_many: writes what the real run writes.

    `fail` names file stems (the link's stem is the row id) to fail;
    `fail_whole_runs` fails every file of any run of more than one, the way
    a run killed for memory does.
    """

    def __init__(self):
        self.calls = []
        self.fail = set()
        self.fail_whole_runs = False

    def __call__(self, sources, output_dir, env=None, timeout=None):
        self.calls.append({
            "sources": [Path(s) for s in sources],
            # Resolved now: the links are cleaned up once the run is over.
            "targets": [Path(s).resolve() for s in sources],
            "env": env,
        })
        output_dir.mkdir(parents=True, exist_ok=True)
        out = {}
        for source in sources:
            source = Path(source)
            if (self.fail_whole_runs and len(sources) > 1) or source.stem in self.fail:
                out[str(source)] = intake_worker.deid.DeidError("killed by SIGKILL")
                continue
            produced = output_dir / f"{source.stem}_deid{source.suffix}"
            produced.write_bytes(b"%PDF-1.4 redacted")
            (output_dir / f"{source.stem}_deid.txt").write_text("redacted text")
            (output_dir / f"{source.stem}_deid.report.json").write_text("{}")
            out[str(source)] = produced
        return out


@pytest.fixture
def pipeline(monkeypatch):
    fake = Pipeline()
    monkeypatch.setattr(intake_worker.deid, "run_pipeline_many", fake)
    monkeypatch.setattr(intake_worker, "embed_metadata", lambda *a, **kw: None)
    return fake


def _queued(cursor):
    return crud.list_files(cursor, status="queued")


def _by_name(cursor, name):
    return next(r for r in crud.list_files(cursor) if r.file_name == name)


def _claim(cursor, record):
    crud.update_file(cursor, record.id, IntakeFileUpdate(status="processing"))
    return crud.get_file(cursor, record.id)


# --- one file ----------------------------------------------------------


def test_the_redacted_copy_lands_in_the_mirror_under_the_code(swept, cursor, pipeline):
    record = _claim(cursor, _by_name(cursor, "image.pdf"))

    assert intake_worker.redact_one(record)

    after = crud.get_file(cursor, record.id)
    assert after.status == "done"
    output = swept / intake.deidentified_dir_name() / "A/B/C/AA1234" / after.output_name
    assert output.is_file(), f"not at {output}"
    assert after.output_name.startswith("AA1234_")
    assert after.output_name.endswith(".pdf")


def test_the_run_s_sidecars_are_renamed_with_the_copy(swept, cursor, pipeline):
    record = _claim(cursor, _by_name(cursor, "image.pdf"))
    intake_worker.redact_one(record)
    after = crud.get_file(cursor, record.id)

    stem = after.output_name.rsplit(".", 1)[0]
    folder = swept / intake.deidentified_dir_name() / "A/B/C/AA1234"
    assert {p.name for p in folder.iterdir()} == {
        f"{stem}.pdf", f"{stem}.txt", f"{stem}.report.json"
    }


def test_the_original_is_left_where_it_was(swept, cursor, pipeline):
    record = _claim(cursor, _by_name(cursor, "image.pdf"))
    intake_worker.redact_one(record)

    assert (swept / "A/B/C/AA1234/image.pdf").is_file()


def test_a_file_that_has_gone_missing_fails_rather_than_crashing(swept, cursor, pipeline):
    record = _claim(cursor, _by_name(cursor, "image.pdf"))
    (swept / record.relative_path).unlink()

    assert not intake_worker.redact_one(record)

    after = crud.get_file(cursor, record.id)
    assert after.status == "failed"
    assert "no longer at the path" in after.detail


def test_a_pipeline_failure_is_recorded_on_the_row(swept, cursor, pipeline):
    record = _claim(cursor, _by_name(cursor, "image.pdf"))
    pipeline.fail.add(record.id)

    assert not intake_worker.redact_one(record)

    after = crud.get_file(cursor, record.id)
    assert after.status == "failed"
    assert "SIGKILL" in after.detail


def test_the_file_goes_in_under_the_type_found_in_its_bytes(
    tmp_path, cursor, patched_hive, pipeline, monkeypatch
):
    """A PACS export called IM000001 has no extension; the pipeline picks
    its reader by extension, so without this it would refuse the file."""
    from tests.test_filetype import DICOM_BYTES

    monkeypatch.setenv("INTAKE_DIR", str(tmp_path))
    _drop(tmp_path, "A/AA1234/IM000001", data=DICOM_BYTES)
    intake.sweep(cursor, root=tmp_path, dry_run=False)
    record = _claim(cursor, _queued(cursor)[0])

    intake_worker.redact_one(record)

    assert pipeline.calls[0]["sources"][0].suffix == ".dcm"
    assert pipeline.calls[0]["targets"][0] == (tmp_path / "A/AA1234/IM000001").resolve()


def test_two_files_with_one_name_in_one_run_do_not_collide(
    tmp_path, cursor, patched_hive, pipeline, monkeypatch
):
    """A run writes into one folder; `image.dcm` from two series must not
    overwrite each other there."""
    monkeypatch.setenv("INTAKE_DIR", str(tmp_path))
    _drop(tmp_path, "A/AA1234/s1/image.pdf", data=b"%PDF-1.4 one")
    _drop(tmp_path, "A/AA1234/s2/image.pdf", data=b"%PDF-1.4 two")
    intake.sweep(cursor, root=tmp_path, dry_run=False)

    result = intake_worker.drain(pool_size=1, check_settled=False, root=tmp_path)

    assert result["done"] == 2
    mirror = tmp_path / intake.deidentified_dir_name() / "A" / "AA1234"
    assert len(list((mirror / "s1").glob("*.pdf"))) == 1
    assert len(list((mirror / "s2").glob("*.pdf"))) == 1


# --- chunks ------------------------------------------------------------


def test_many_files_go_through_in_one_run(swept, cursor, pipeline):
    """The point of chunking: models load once per run, not once per file --
    with one worker, everything it claims goes in one run."""
    result = intake_worker.drain(pool_size=1, check_settled=False, root=swept)

    assert result["done"] == 3
    assert len(pipeline.calls) == 1, "each file was given its own run"


def test_dicoms_run_together_and_documents_in_small_groups(monkeypatch):
    monkeypatch.setenv("DEID_CHUNK_DICOM", "40")
    monkeypatch.setenv("DEID_CHUNK_DOCUMENTS", "2")

    class Row:
        def __init__(self, n, ext):
            self.id, self.file_extension = f"id{n}", ext

    rows = [Row(n, "dcm") for n in range(5)] + [Row(n + 5, "pdf") for n in range(3)]
    units = intake_worker._units(rows)

    assert [(len(unit), batch) for unit, batch in units] == [(5, 5), (2, 1), (1, 1)]


def test_a_few_files_are_spread_across_every_worker(monkeypatch):
    """Three PDFs packed into one run left one worker doing all three while
    the others sat idle."""
    monkeypatch.setenv("DEID_CHUNK_DOCUMENTS", "4")

    class Row:
        def __init__(self, n, ext):
            self.id, self.file_extension = f"id{n}", ext

    units = intake_worker._units([Row(n, "pdf") for n in range(3)], workers=3)

    assert [len(unit) for unit, _ in units] == [1, 1, 1]


def test_a_big_queue_still_fills_each_run(monkeypatch):
    """Spreading must not shrink runs when there is plenty: the models load
    once per run, which is where the speed comes from."""
    monkeypatch.setenv("DEID_CHUNK_DICOM", "40")

    class Row:
        def __init__(self, n):
            self.id, self.file_extension = f"id{n}", "dcm"

    units = intake_worker._units([Row(n) for n in range(240)], workers=6)

    assert [len(unit) for unit, _ in units] == [40] * 6


def test_every_worker_runs_at_once_on_a_small_push(swept, cursor, monkeypatch):
    """Three files, three workers: three pipeline runs going at the same time."""
    running, peak = [0], [0]
    lock = threading.Lock()
    gate = threading.Barrier(3, timeout=5)

    def fake(sources, output_dir, env=None, timeout=None):
        with lock:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
        try:
            gate.wait()
        except threading.BrokenBarrierError:
            pass
        output_dir.mkdir(parents=True, exist_ok=True)
        out = {}
        for source in sources:
            produced = output_dir / f"{source.stem}_deid{source.suffix}"
            produced.write_bytes(b"redacted")
            out[str(source)] = produced
        with lock:
            running[0] -= 1
        return out

    monkeypatch.setattr(intake_worker.deid, "run_pipeline_many", fake)
    monkeypatch.setattr(intake_worker, "embed_metadata", lambda *a, **kw: None)

    result = intake_worker.drain(pool_size=3, check_settled=False, root=swept)

    assert result["done"] == 3
    assert peak[0] == 3, f"only {peak[0]} worker(s) were ever busy at once"


def test_one_bad_file_in_a_run_does_not_fail_the_rest(swept, cursor, pipeline):
    """A run killed outright fails every file in it. The good ones are run
    again on their own; only the one that really fails is marked failed."""
    bad = _by_name(cursor, "second.pdf")
    pipeline.fail_whole_runs = True
    pipeline.fail.add(bad.id)

    result = intake_worker.drain(pool_size=1, check_settled=False, root=swept)

    assert result["done"] == 2
    assert result["failed"] == 1
    assert crud.get_file(cursor, bad.id).status == "failed"


def test_draining_redacts_everything_queued(swept, cursor, pipeline):
    result = intake_worker.drain(check_settled=False, root=swept)

    assert result["claimed"] == 3
    assert result["done"] == 3
    tally = crud.counts(cursor)
    assert tally.done == 3
    assert tally.queued == 0
    assert tally.skipped == 1, "a skipped file was redacted"


def test_a_limit_stops_after_that_many_files(swept, cursor, pipeline):
    result = intake_worker.drain(limit=1, check_settled=False, root=swept)

    assert result["claimed"] == 1
    assert crud.counts(cursor).queued == 2


def test_several_workers_never_share_a_file(swept, cursor, pipeline, monkeypatch):
    monkeypatch.setenv("DEID_CHUNK_DICOM", "1")  # one file per claim, so all 3 threads work
    result = intake_worker.drain(pool_size=3, check_settled=False, root=swept)

    handed = [str(t) for call in pipeline.calls for t in call["targets"]]
    assert result["done"] == 3
    assert len(handed) == len(set(handed)), "a file was redacted twice"


def test_nothing_queued_drains_to_nothing(cursor, patched_hive, tmp_path, pipeline):
    result = intake_worker.drain(root=tmp_path)

    assert result == {"done": 0, "failed": 0, "claimed": 0, "workers": result["workers"]}


# --- claiming ----------------------------------------------------------


def test_claiming_marks_the_rows_so_nothing_else_takes_them(swept, cursor):
    prefixes = intake_worker.shard_prefixes()
    first = intake_worker.claim_chunk(cursor, prefixes, 2)

    assert len(first) == 2
    assert all(crud.get_file(cursor, r.id).status == "processing" for r in first)

    second = intake_worker.claim_chunk(cursor, prefixes, 2)
    assert {r.id for r in first}.isdisjoint({r.id for r in second})


def test_a_file_still_being_written_is_not_claimed(swept, cursor, monkeypatch):
    monkeypatch.setenv("INTAKE_SETTLE_SECONDS", "3600")

    assert intake_worker.claim_chunk(cursor, intake_worker.shard_prefixes(), 10) == []
    assert len(_queued(cursor)) == 3, "a row was taken anyway"


def test_a_batch_marker_overrides_the_settle_wait(swept, cursor, monkeypatch):
    monkeypatch.setenv("INTAKE_SETTLE_SECONDS", "3600")
    (swept / "A/B/C/AA1234" / intake.BATCH_MARKER).write_text("")

    claimed = intake_worker.claim_chunk(cursor, intake_worker.shard_prefixes(), 10)

    assert {r.file_name for r in claimed} == {"image.pdf", "second.pdf"}


# --- shards ------------------------------------------------------------


def test_shards_split_the_work_with_no_overlap_and_no_gap():
    of = 12
    owned = [set(intake_worker.shard_prefixes([k], of)) for k in range(of)]

    for a in range(of):
        for b in range(a + 1, of):
            assert owned[a].isdisjoint(owned[b]), f"shards {a} and {b} overlap"
    assert set().union(*owned) == set(intake_worker.PREFIXES)


def test_a_process_only_claims_inside_its_shards(swept, cursor):
    """What keeps processes on different machines off each other's files."""
    rows = _queued(cursor)
    mine = intake_worker.shard_prefixes([0], 2)
    theirs = intake_worker.shard_prefixes([1], 2)

    got_mine = intake_worker.claim_chunk(cursor, mine, 10)
    got_theirs = intake_worker.claim_chunk(cursor, theirs, 10)

    assert all(r.id[:2] in mine for r in got_mine)
    assert all(r.id[:2] in theirs for r in got_theirs)
    assert len(got_mine) + len(got_theirs) == len(rows)


def test_recovery_only_touches_its_own_shard(swept, cursor):
    """Another machine may be mid-way through the rest."""
    for record in _queued(cursor):
        crud.update_file(cursor, record.id, IntakeFileUpdate(status="processing"))
    mine = intake_worker.shard_prefixes([0], 2)

    intake_worker.recover(cursor, swept, mine)

    for record in crud.list_files(cursor):
        if record.status in ("queued", "processing"):
            expected = "queued" if record.id[:2] in mine else "processing"
            assert record.status == expected


# --- the journal -------------------------------------------------------


def test_outcomes_are_journalled_and_cleared_once_recorded(swept, cursor, pipeline):
    intake_worker.drain(pool_size=1, check_settled=False, root=swept)

    journals = list((swept / ".intake" / "journal").glob("*.jsonl"))
    assert journals == [], "a published journal was left behind"


def test_work_a_killed_worker_finished_is_not_done_again(swept, cursor, pipeline):
    """Killed after its OCR finished but before Hive heard: the journal holds
    the outcome, and the next start publishes it instead of redoing it."""
    record = _claim(cursor, _by_name(cursor, "image.pdf"))
    journal = swept / ".intake" / "journal" / f"{intake_worker.socket.gethostname()}-999999-t0.jsonl"
    journal.parent.mkdir(parents=True)
    journal.write_text(json.dumps({
        "id": record.id, "status": "done", "output_path": "/mirror/AA1234_x.pdf",
        "output_name": "AA1234_x.pdf", "detail": None,
    }) + "\n")

    intake_worker.recover(cursor, swept, intake_worker.shard_prefixes())

    after = crud.get_file(cursor, record.id)
    assert after.status == "done", "finished work was requeued"
    assert after.output_name == "AA1234_x.pdf"
    assert not journal.exists()
    assert pipeline.calls == []


def test_a_live_worker_s_journal_is_left_alone(swept, cursor, pipeline):
    record = _claim(cursor, _by_name(cursor, "image.pdf"))
    journal = swept / ".intake" / "journal" / f"{intake_worker.worker_name()}-t0.jsonl"
    journal.parent.mkdir(parents=True)
    journal.write_text(json.dumps({"id": record.id, "status": "done",
                                   "output_path": "x", "output_name": "x", "detail": None}) + "\n")

    intake_worker.replay_journals(cursor, swept)

    assert journal.exists(), "a running worker's journal was taken from it"


def test_a_half_written_journal_line_is_skipped(tmp_path):
    path = tmp_path / "j.jsonl"
    path.write_text('{"id": "a", "status": "done"}\n{"id": "b", "sta')

    assert [r["id"] for r in intake_worker.Journal.read(path)] == ["a"]


def test_a_refused_write_is_retried(swept, cursor, monkeypatch):
    """Hive can abort a write that races another; the outcome is safe in
    the journal meanwhile, so trying again is always right."""
    record = _by_name(cursor, "image.pdf")
    real = crud.apply_results
    attempts = []

    def flaky(cur, results):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("Transaction manager has aborted the transaction")
        return real(cur, results)

    monkeypatch.setattr(intake_worker.crud, "apply_results", flaky)
    monkeypatch.setattr(intake_worker.time, "sleep", lambda s: None)

    intake_worker._publish(cursor, [{"id": record.id, "status": "done",
                                     "output_path": "p", "output_name": "n", "detail": None}])

    assert len(attempts) == 2
    assert crud.get_file(cursor, record.id).status == "done"


# --- the heartbeat -----------------------------------------------------


def test_a_worker_reports_what_it_did(swept, cursor, pipeline):
    intake_worker.drain(pool_size=1, check_settled=False, root=swept)

    beats = intake_worker.read_heartbeats(swept)
    assert len(beats) == 1
    beat = beats[0]
    assert beat["done"] == 3
    assert beat["status"] == "idle"
    assert sum(beat["per_minute"].values()) == 3


def test_a_heartbeat_names_its_shards(tmp_path):
    beat = intake_worker.Heartbeat(tmp_path, [2, 5], 12, 3).start()
    beat.stop()

    written = intake_worker.read_heartbeats(tmp_path)[0]
    assert written["shards"] == [2, 5]
    assert written["of"] == 12
    assert written["workers"] == 3


# --- sizing ------------------------------------------------------------


def test_one_worker_by_default(monkeypatch):
    monkeypatch.delenv("DEID_WORKERS", raising=False)
    assert intake_worker.workers() == 1


def test_the_worker_count_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("DEID_WORKERS", "6")
    assert intake_worker.workers() == 6


def test_a_nonsense_worker_count_is_at_least_one(monkeypatch):
    monkeypatch.setenv("DEID_WORKERS", "0")
    assert intake_worker.workers() == 1


def test_each_worker_is_given_its_own_cpu_budget(monkeypatch):
    monkeypatch.setenv("DEID_WORKER_CPU_THREADS", "2")
    env = intake_worker._subprocess_env()
    assert env["OCR_CPU_THREADS"] == env["OMP_NUM_THREADS"] == env["MKL_NUM_THREADS"] == "2"


def test_the_budget_and_batch_size_reach_the_pipeline(swept, cursor, pipeline, monkeypatch):
    monkeypatch.setenv("DEID_WORKER_CPU_THREADS", "3")
    intake_worker.drain(pool_size=1, check_settled=False, root=swept)

    env = pipeline.calls[0]["env"]
    assert env["OCR_CPU_THREADS"] == "3"
    assert env["DEID_OCR_BATCH_SIZE"] == "1", "documents must be OCR'd one at a time"


def test_the_pool_is_capped_by_the_memory_the_machine_has(monkeypatch):
    monkeypatch.setenv("DEID_WORKERS", "8")
    monkeypatch.setenv("DEID_WORKER_MEMORY_GB", "6")
    monkeypatch.setattr(intake_worker, "_available_memory_gb", lambda: 13.0)
    assert intake_worker.safe_worker_count() == 2


def test_without_a_memory_figure_the_count_is_taken_as_given(monkeypatch):
    monkeypatch.setenv("DEID_WORKERS", "4")
    monkeypatch.delenv("DEID_WORKER_MEMORY_GB", raising=False)
    assert intake_worker.safe_worker_count() == 4


def test_a_restarted_worker_keeps_its_history(tmp_path):
    """A scheduled Job is a new process every minute; its speed must not
    reset to zero each time, and it must not leave a file per run."""
    first = intake_worker.Heartbeat(tmp_path, [0], 1, 1).start()
    first.finished(5, 1)
    first.stop()

    second = intake_worker.Heartbeat(tmp_path, [0], 1, 1).start()
    second.finished(2, 0)
    second.stop()

    beats = intake_worker.read_heartbeats(tmp_path)
    assert len(beats) == 1
    assert beats[0]["done"] == 7
    assert beats[0]["failed"] == 1
    assert sum(beats[0]["per_minute"].values()) == 8


def test_which_way_a_dicom_went_is_kept_for_audit(swept, cursor, monkeypatch):
    """Pixels redacted, or tags only because the image held no text."""
    record = _claim(cursor, _by_name(cursor, "image.pdf"))

    def fake(sources, output_dir, env=None, timeout=None):
        output_dir.mkdir(parents=True, exist_ok=True)
        out = {}
        for source in sources:
            produced = output_dir / f"{source.stem}_deid{source.suffix}"
            produced.write_bytes(b"redacted")
            out[str(source)] = intake_worker.deid.Produced(
                produced, "tags only: no text in the image"
            )
        return out

    monkeypatch.setattr(intake_worker.deid, "run_pipeline_many", fake)
    monkeypatch.setattr(intake_worker, "embed_metadata", lambda *a, **kw: None)

    intake_worker.redact_one(record)

    assert crud.get_file(cursor, record.id).detail == "tags only: no text in the image"
