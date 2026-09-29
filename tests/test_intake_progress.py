"""How far along, how fast, how long to go -- and whether it has stopped."""

import json
import time

import pytest

from app import intake, intake_progress, intake_worker
from app.crud import intake_files as crud
from app.schemas import IntakeFileUpdate


def _drop(root, relative, data=b"%PDF-1.4 fake"):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


@pytest.fixture(autouse=True)
def fresh_cache():
    intake_progress.clear_cache()
    yield
    intake_progress.clear_cache()


@pytest.fixture
def drop(tmp_path, cursor, patched_hive, monkeypatch):
    monkeypatch.setenv("INTAKE_DIR", str(tmp_path))
    for n in range(6):
        _drop(tmp_path, f"A/AA1234/s{n}.pdf", data=f"%PDF-1.4 {n}".encode())
    _drop(tmp_path, "loose/nocode.pdf", data=b"%PDF-1.4 x")
    intake.sweep(cursor, root=tmp_path, dry_run=False)
    return tmp_path


def _set(cursor, n, status):
    for record in crud.list_files(cursor, status="queued")[:n]:
        crud.update_file(cursor, record.id, IntakeFileUpdate(status=status))


def _beat(root, name, *, seen_ago=0.0, per_minute=None, status="working"):
    path = root / ".intake" / "workers" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "name": name, "host": "h", "shards": [0], "of": 1, "workers": 3,
        "last_seen": time.time() - seen_ago, "status": status,
        "current": ["s1.pdf"], "done": 10, "failed": 1,
        "per_minute": per_minute or {},
    }))


def _minutes_ago(n):
    return str(int(time.time() // 60 * 60) - n * 60)


def test_progress_counts_the_work_not_what_waits_on_a_person(drop, cursor):
    _set(cursor, 3, "done")
    _set(cursor, 1, "failed")

    p = intake_progress.progress(cursor, drop)

    assert p["total"] == 6, "a skipped file was counted as work"
    assert p["finished"] == 4
    assert p["remaining"] == 2
    assert p["percent"] == pytest.approx(66.67, abs=0.01)
    assert p["needs_a_person"] == 1


def test_speed_comes_from_the_workers_last_quarter_hour(drop, cursor):
    per_minute = {_minutes_ago(m): 30 for m in range(1, 16)}  # 30/min for 15 min
    per_minute[_minutes_ago(0)] = 5  # the minute in progress is left out
    per_minute[_minutes_ago(30)] = 999  # outside the window
    _beat(drop, "w1", per_minute=per_minute)

    p = intake_progress.progress(cursor, drop)

    assert p["per_hour"] == 1800


def test_time_remaining_is_what_is_left_at_the_current_speed(drop, cursor):
    _beat(drop, "w1", per_minute={_minutes_ago(m): 2 for m in range(1, 16)})  # 2/min

    p = intake_progress.progress(cursor, drop)

    assert p["remaining"] == 6
    assert p["eta_seconds"] == 180  # 6 files at 2 a minute


def test_no_speed_yet_means_no_guess(drop, cursor):
    assert intake_progress.progress(cursor, drop)["eta_seconds"] is None


def test_work_waiting_with_no_live_worker_is_stalled(drop, cursor):
    _beat(drop, "w1", seen_ago=intake_worker.HEARTBEAT_STALE_SECONDS + 120)

    p = intake_progress.progress(cursor, drop)

    assert p["stalled"] is True
    assert "no worker has reported for" in p["stalled_reason"]
    assert p["workers"][0]["status"] == "stopped"


def test_work_waiting_with_no_worker_ever_is_stalled(drop, cursor):
    p = intake_progress.progress(cursor, drop)

    assert p["stalled"] is True
    assert "no worker has reported yet" in p["stalled_reason"]


def test_a_live_worker_means_not_stalled(drop, cursor):
    _beat(drop, "w1", seen_ago=10)

    p = intake_progress.progress(cursor, drop)

    assert p["stalled"] is False
    assert p["workers"][0]["alive"] is True


def test_nothing_waiting_is_never_stalled(drop, cursor):
    _set(cursor, 6, "done")

    assert intake_progress.progress(cursor, drop)["stalled"] is False


def test_each_push_has_its_own_progress(drop, cursor):
    _set(cursor, 3, "done")

    batches = intake_progress.batches(cursor)

    assert len(batches) == 1
    assert batches[0]["total"] == 6
    assert batches[0]["finished"] == 3
    assert batches[0]["percent"] == 50.0


def test_counts_are_one_query_not_a_load_of_every_row(drop, cursor):
    before = len(cursor.statements)
    intake_progress.progress(cursor, drop)
    queries = [sql for sql, _ in cursor.statements[before:]]

    assert len(queries) == 1
    assert "GROUP BY" in queries[0]


def test_counts_are_cached_between_polls(drop, cursor):
    """Every open Intake page polls; each poll must not be a Hive query."""
    intake_progress.progress(cursor, drop)
    before = len(cursor.statements)

    intake_progress.progress(cursor, drop)

    assert len(cursor.statements) == before


# --- the API ------------------------------------------------------------


def test_the_progress_endpoint(as_admin, drop, cursor):
    body = as_admin.get("/intake/progress").json()

    assert body["total"] == 6
    assert body["stalled"] is True


def test_long_lists_come_a_page_at_a_time(as_admin, drop, cursor):
    first = as_admin.get("/intake/files", params={"status": "queued", "limit": 4})
    second = as_admin.get(
        "/intake/files", params={"status": "queued", "limit": 4, "offset": 4}
    )

    assert first.headers["X-Total-Count"] == "6"
    assert len(first.json()) == 4
    assert len(second.json()) == 2
    ids = {r["id"] for r in first.json()} | {r["id"] for r in second.json()}
    assert len(ids) == 6, "a page repeated or skipped a row"


def test_a_page_is_never_unbounded(as_admin, drop, cursor):
    response = as_admin.get("/intake/files", params={"status": "queued", "limit": 999999})

    assert response.status_code == 200
    assert len(response.json()) == 6


def test_the_whole_list_downloads_as_csv(as_admin, drop, cursor):
    """Not just the page on screen -- every skipped file, for whoever has to
    fix them at source."""
    response = as_admin.get("/intake/files/export", params={"status": "queued"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    lines = response.text.strip().splitlines()
    assert lines[0].startswith("source_path,status,reason")
    assert len(lines) == 1 + 6


def test_the_download_pages_through_hive(as_admin, drop, cursor, monkeypatch):
    from app.routers import intake as router

    monkeypatch.setattr(router, "EXPORT_PAGE", 4)
    lines = as_admin.get("/intake/files/export", params={"status": "queued"}).text.strip().splitlines()

    assert len(lines) == 1 + 6, "a page was lost or repeated"


def test_a_run_younger_than_the_window_is_not_diluted(drop, cursor):
    """Two minutes of work averaged over fifteen would read at a seventh of
    its speed -- and the time left at seven times too long."""
    _beat(drop, "w1", per_minute={_minutes_ago(1): 60, _minutes_ago(2): 60})

    assert intake_progress.progress(cursor, drop)["per_hour"] == 3600


def test_a_push_with_no_rows_left_is_not_listed(drop, cursor):
    crud.create_batch(cursor, "/somewhere/else")

    assert len(intake_progress.batches(cursor)) == 1
