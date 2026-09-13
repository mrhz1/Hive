import json
import sys
import time
from pathlib import Path

import pytest

from app import deid_progress

OCR_ROOT = Path(__file__).resolve().parent.parent / "OCR"
if str(OCR_ROOT) not in sys.path:
    sys.path.insert(0, str(OCR_ROOT))

from deid.progress import NullProgress, ProgressWriter, writer  # noqa: E402


@pytest.fixture
def progress_file(tmp_path, monkeypatch):
    directory = tmp_path / ".progress"
    monkeypatch.setattr(deid_progress, "PROGRESS_DIR", directory)
    return directory / "file-1.json"


def _state(path):
    return json.loads(path.read_text(encoding="utf-8"))




def test_page_updates_advance_the_percentage(progress_file):
    w = ProgressWriter(str(progress_file))
    w.document(0, "/storage/scan.pdf", 100)

    assert _state(progress_file)["page_total"] == 100
    assert _state(progress_file)["percent"] == 0.0

    for page in (10, 50):
        w._last_write = 0.0
        w.page(page)

    assert _state(progress_file)["page"] == 50
    assert _state(progress_file)["percent"] == pytest.approx(48.5, abs=0.1)


def test_ocr_never_reports_completion(progress_file):
    w = ProgressWriter(str(progress_file))
    w.document(0, "/storage/scan.pdf", 20)
    w._last_write = 0.0
    w.page(20)

    assert _state(progress_file)["percent"] < 100.0

    w.finish()
    assert _state(progress_file)["percent"] == 100.0
    assert _state(progress_file)["stage"] == "done"


def test_percentage_spans_a_multi_document_run(progress_file):
    w = ProgressWriter(str(progress_file), file_total=2)

    w.document(0, "/storage/a.pdf", 10)
    w._last_write = 0.0
    w.page(10)
    halfway = _state(progress_file)["percent"]

    w.document(1, "/storage/b.pdf", 10)
    w._last_write = 0.0
    w.page(5)

    assert halfway == pytest.approx(48.5, abs=0.1)
    assert _state(progress_file)["percent"] > halfway


def test_writes_are_throttled(progress_file):
    w = ProgressWriter(str(progress_file))
    w.document(0, "/storage/scan.dcm", 500)

    for page in range(1, 200):
        w.page(page)

    assert _state(progress_file)["page"] == 0


def test_a_failed_write_never_raises(progress_file, monkeypatch):
    w = ProgressWriter(str(progress_file))

    def explode(_state):
        raise OSError("disk full")

    monkeypatch.setattr(w, "_write", explode)

    w.document(0, "/storage/scan.pdf", 10)
    w.page(1)
    w.finish()


def test_null_writer_accepts_the_same_calls():
    n = writer(None)
    assert isinstance(n, NullProgress)
    n.document(0, "/x.pdf", 3)
    n.page(1)
    n.stage("redacting")
    n.finish()




def test_reader_sees_what_the_writer_wrote(progress_file):
    w = ProgressWriter(str(progress_file))
    w.document(0, "/storage/scan.pdf", 100)
    w._last_write = 0.0
    w.page(41)

    state = deid_progress.read("file-1")

    assert state["stage"] == "ocr"
    assert state["page"] == 41
    assert state["page_total"] == 100


def test_missing_progress_is_not_an_error(progress_file):
    assert deid_progress.read("file-that-never-ran") is None


def test_unparsable_progress_is_not_an_error(progress_file):
    progress_file.parent.mkdir(parents=True, exist_ok=True)
    progress_file.write_text("{ truncated", encoding="utf-8")

    assert deid_progress.read("file-1") is None


def test_a_killed_job_goes_stale_rather_than_freezing(progress_file):
    w = ProgressWriter(str(progress_file))
    w.document(0, "/storage/scan.pdf", 100)
    w._last_write = 0.0
    w.page(41)

    state = _state(progress_file)
    state["updated_at"] = time.time() - deid_progress.STALE_AFTER_SECONDS - 1
    progress_file.write_text(json.dumps(state), encoding="utf-8")

    assert deid_progress.read("file-1") is None


def test_a_finished_run_does_not_go_stale(progress_file):
    w = ProgressWriter(str(progress_file))
    w.document(0, "/storage/scan.pdf", 100)
    w.finish()

    state = _state(progress_file)
    state["updated_at"] = time.time() - deid_progress.STALE_AFTER_SECONDS - 1
    progress_file.write_text(json.dumps(state), encoding="utf-8")

    assert deid_progress.read("file-1")["stage"] == "done"


def test_file_id_cannot_climb_out_of_the_progress_directory(progress_file):
    path = deid_progress.progress_path("../../etc/passwd")

    assert path.parent == deid_progress.PROGRESS_DIR
    assert ".." not in path.name


def test_clear_is_idempotent(progress_file):
    w = ProgressWriter(str(progress_file))
    w.document(0, "/storage/scan.pdf", 10)

    deid_progress.clear("file-1")
    deid_progress.clear("file-1")

    assert deid_progress.read("file-1") is None




def _application(client):
    from conftest import minimal_patient

    patient_id = client.post("/patients", json=minimal_patient()).json()["id"]
    return client.post("/applications", json={"patient_id": patient_id}).json()["id"]


def _uploaded_file(client, application_id):
    return client.post(
        f"/applications/{application_id}/files",
        files=[("files", ("scan.pdf", b"%PDF-1.4 fake", "application/pdf"))],
    ).json()[0]


def test_progress_endpoint_reports_a_running_file(
    as_admin, storage_root, tmp_path, monkeypatch
):
    monkeypatch.setattr(deid_progress, "PROGRESS_DIR", tmp_path / ".progress")
    monkeypatch.setattr(
        "app.routers.patient_application_files.dispatch_deidentification",
        lambda **kwargs: None,
    )

    application_id = _application(as_admin)
    record = _uploaded_file(as_admin, application_id)

    as_admin.post(f"/files/{record['id']}/deidentify")

    w = ProgressWriter(str(deid_progress.progress_path(record["id"])))
    w.document(0, "/storage/scan.pdf", 100)
    w._last_write = 0.0
    w.page(41)

    body = as_admin.get(
        f"/applications/{application_id}/files/deid-progress"
    ).json()

    assert len(body["items"]) == 1
    assert body["items"][0]["file_id"] == record["id"]
    assert body["items"][0]["page"] == 41
    assert body["items"][0]["page_total"] == 100


def test_progress_endpoint_is_empty_when_nothing_runs(
    as_admin, storage_root, tmp_path, monkeypatch
):
    monkeypatch.setattr(deid_progress, "PROGRESS_DIR", tmp_path / ".progress")

    application_id = _application(as_admin)
    _uploaded_file(as_admin, application_id)

    body = as_admin.get(
        f"/applications/{application_id}/files/deid-progress"
    ).json()

    assert body["items"] == []


def test_single_file_progress_falls_back_to_status(
    as_admin, storage_root, tmp_path, monkeypatch
):
    monkeypatch.setattr(deid_progress, "PROGRESS_DIR", tmp_path / ".progress")

    application_id = _application(as_admin)
    record = _uploaded_file(as_admin, application_id)

    body = as_admin.get(f"/files/{record['id']}/deid-progress").json()

    assert body["file_id"] == record["id"]
    assert body["stage"] == "starting"
    assert body["percent"] == 0.0


def test_a_failure_keeps_the_page_it_reached(progress_file):
    stage = ProgressWriter(str(progress_file))
    stage.document(0, "/storage/scan.pdf", 100)
    stage._last_write = 0.0
    stage.page(41)

    ProgressWriter(str(progress_file)).adopt().fail("exit -9")

    state = deid_progress.read("file-1")
    assert state["stage"] == "failed"
    assert state["page"] == 41
    assert state["page_total"] == 100
    assert "exit -9" in state["error"]


def test_redaction_keeps_the_page_counts_stage_one_wrote(progress_file):
    stage_one = ProgressWriter(str(progress_file))
    stage_one.document(0, "/storage/scan.pdf", 64)
    stage_one._last_write = 0.0
    stage_one.page(64)

    ProgressWriter(str(progress_file)).adopt().stage("redacting")

    state = deid_progress.read("file-1")
    assert state["stage"] == "redacting"
    assert state["page_total"] == 64
    assert state["source"] == "scan.pdf"
