"""The dispatcher must never ask Cloudera for a second run while one is active -- that request is what CML refuses with `400 job run for job <id> already active`, records as a Skipped entry, and used to leave a perfectly good file marked failed."""
import types

import pytest

from app import deid_queue
from app.cloudera import (
    ClouderaCapacityError,
    ClouderaError,
    _is_busy_response,
    is_terminal_run_status,
)


class Row:
    def __init__(self, file_id, created_at, status="queued"):
        self.id = file_id
        self.created_at = created_at
        self.deid_status = status


@pytest.fixture
def table(monkeypatch):
    """A fake files table the dispatcher reads through crud."""
    rows = {}

    def list_files(_cursor, *a, **kw):
        return list(rows.values())

    def get_file(_cursor, file_id):
        return rows.get(file_id)

    monkeypatch.setattr(deid_queue.crud, "list_files", list_files)
    monkeypatch.setattr(deid_queue.crud, "get_file", get_file)
    monkeypatch.setattr(
        deid_queue, "hive_cursor", lambda: _null_context(), raising=True
    )
    # No real waiting anywhere in these tests.
    monkeypatch.setattr(deid_queue, "POLL_SECONDS", 0)
    monkeypatch.setattr(deid_queue, "ERROR_BACKOFF_SECONDS", 0)
    return rows


def _null_context():
    import contextlib

    return contextlib.nullcontext(None)


def test_runs_are_serialised_never_overlapping(table, monkeypatch):
    """Two files clicked at once: the second run is requested only after the first has finished."""
    table["a"] = Row("a", 1)
    table["b"] = Row("b", 2)

    active = {"count": 0}
    overlaps = []
    order = []

    def start(environment=None):
        file_id = environment["DEID_FILE_ID"]
        order.append(file_id)
        active["count"] += 1
        if active["count"] > 1:
            overlaps.append(file_id)
        return f"run-{file_id}"

    def run_status(run_id):
        # The run ends, and the worker marks the row done, between polls.
        file_id = run_id.split("-", 1)[1]
        table[file_id].deid_status = "done"
        active["count"] -= 1
        return "ENGINE_SUCCEEDED"

    monkeypatch.setattr(deid_queue, "start_deid_job_run", start)
    monkeypatch.setattr(deid_queue, "get_job_run_status", run_status)

    assert deid_queue.drain_once() is True
    assert deid_queue.drain_once() is True
    assert deid_queue.drain_once() is False  # queue empty

    assert order == ["a", "b"], "oldest queued file must go first"
    assert overlaps == [], "a run was requested while another was active"


def test_fifo_by_click_time(table, monkeypatch):
    """Order is by created_at, not by whatever the table hands back."""
    table["late"] = Row("late", 99)
    table["early"] = Row("early", 1)
    table["mid"] = Row("mid", 50)

    order = []

    def start(environment=None):
        file_id = environment["DEID_FILE_ID"]
        order.append(file_id)
        table[file_id].deid_status = "done"
        return "r"

    monkeypatch.setattr(deid_queue, "start_deid_job_run", start)
    monkeypatch.setattr(deid_queue, "get_job_run_status", lambda r: "ENGINE_SUCCEEDED")

    while deid_queue.drain_once():
        pass

    assert order == ["early", "mid", "late"]


def test_dispatch_error_leaves_row_queued(table, monkeypatch):
    """A control-plane problem is not the file's fault: the row stays claimable instead of being marked failed."""
    table["a"] = Row("a", 1)

    def start(environment=None):
        raise ClouderaError("400: something the control plane did not like")

    monkeypatch.setattr(deid_queue, "start_deid_job_run", start)

    deid_queue.drain_once()

    assert table["a"].deid_status == "queued"


def test_busy_response_is_deferred_not_failed(table, monkeypatch):
    table["a"] = Row("a", 1)

    def start(environment=None):
        raise ClouderaCapacityError("job run for job x already active, code 9")

    monkeypatch.setattr(deid_queue, "start_deid_job_run", start)

    deid_queue.drain_once()

    assert table["a"].deid_status == "queued"


def test_unreadable_run_status_does_not_end_the_wait(table, monkeypatch):
    """An unreachable control plane must read as still-running, or the dispatcher races ahead and starts the overlapping run."""
    table["a"] = Row("a", 1)
    polls = {"n": 0}

    def run_status(run_id):
        polls["n"] += 1
        if polls["n"] < 3:
            return ""  # cannot tell
        table["a"].deid_status = "done"
        return "ENGINE_SUCCEEDED"

    monkeypatch.setattr(deid_queue, "start_deid_job_run", lambda environment=None: "r")
    monkeypatch.setattr(deid_queue, "get_job_run_status", run_status)

    deid_queue.drain_once()

    assert polls["n"] >= 3, "gave up while the run status was unknown"
    assert table["a"].deid_status == "done"


def test_run_that_dies_without_writing_the_row_is_not_waited_on_forever(
    table, monkeypatch
):
    table["a"] = Row("a", 1)

    monkeypatch.setattr(deid_queue, "start_deid_job_run", lambda environment=None: "r")
    monkeypatch.setattr(deid_queue, "get_job_run_status", lambda r: "ENGINE_FAILED")

    deid_queue.drain_once()

    assert table["a"].deid_status == "queued"


def test_pending_rows_are_not_dispatched(table, monkeypatch):
    """`pending` is the state every upload starts in; only an explicit click (`queued`) means somebody asked."""
    table["a"] = Row("a", 1, status="pending")

    monkeypatch.setattr(
        deid_queue,
        "start_deid_job_run",
        lambda environment=None: pytest.fail("dispatched a pending row"),
    )

    assert deid_queue.drain_once() is False


@pytest.mark.parametrize(
    "body",
    [
        "job run for job abc-123 already active, code 9",
        '{"message":"job run for job x already active","code":9}',
    ],
)
def test_cml_busy_wording_is_recognised(body):
    assert _is_busy_response(body) is True


@pytest.mark.parametrize(
    "status,terminal",
    [
        ("ENGINE_SUCCEEDED", True),
        ("ENGINE_FAILED", True),
        ("ENGINE_TIMEDOUT", True),
        ("ENGINE_STOPPED", True),
        ("ENGINE_RUNNING", False),
        ("ENGINE_SCHEDULING", False),
        ("", False),
        ("something_new", False),
    ],
)
def test_terminal_run_status(status, terminal):
    assert is_terminal_run_status(status) is terminal


def test_five_files_produce_exactly_five_runs(table, monkeypatch):
    """The reported bug."""
    for n in range(5):
        table[f"f{n}"] = Row(f"f{n}", n)

    runs = []
    live = {"run": None}

    def start(environment=None):
        file_id = environment["DEID_FILE_ID"]
        assert live["run"] is None, f"run started while {live['run']} was active"
        run_id = f"run-{file_id}"
        live["run"] = run_id
        runs.append(run_id)
        table[file_id].deid_status = "done"
        return run_id

    polls = {"n": 0}

    def run_status(run_id):
        polls["n"] += 1
        # Still running for a couple of polls after the row went done.
        if polls["n"] % 3 != 0:
            return "ENGINE_RUNNING"
        live["run"] = None
        return "ENGINE_SUCCEEDED"

    monkeypatch.setattr(deid_queue, "start_deid_job_run", start)
    monkeypatch.setattr(deid_queue, "get_job_run_status", run_status)

    while deid_queue.drain_once():
        pass

    assert len(runs) == 5, f"expected one run per file, got {len(runs)}: {runs}"
    assert runs == [f"run-f{n}" for n in range(5)]


def test_a_done_row_does_not_end_the_wait_while_the_run_is_alive(
    table, monkeypatch
):
    table["a"] = Row("a", 1)
    table["b"] = Row("b", 2)

    polls = {"n": 0}

    def start(environment=None):
        file_id = environment["DEID_FILE_ID"]
        table[file_id].deid_status = "done"  # done immediately
        return f"run-{file_id}"

    def run_status(run_id):
        polls["n"] += 1
        return "ENGINE_RUNNING" if polls["n"] < 4 else "ENGINE_SUCCEEDED"

    monkeypatch.setattr(deid_queue, "start_deid_job_run", start)
    monkeypatch.setattr(deid_queue, "get_job_run_status", run_status)

    deid_queue.drain_once()

    assert polls["n"] >= 4, "stopped waiting as soon as the row said done"


def test_a_silent_control_plane_eventually_lets_the_row_decide(
    table, monkeypatch
):
    """An outage must not strand the queue forever -- but it takes a run of unreadable polls, not one, so a blip cannot cause an overlap."""
    table["a"] = Row("a", 1)
    monkeypatch.setattr(deid_queue, "UNREADABLE_POLLS_BEFORE_ROW", 3)

    polls = {"n": 0}

    def start(environment=None):
        table["a"].deid_status = "done"
        return "run-a"

    def run_status(run_id):
        polls["n"] += 1
        return ""  # control plane unreachable

    monkeypatch.setattr(deid_queue, "start_deid_job_run", start)
    monkeypatch.setattr(deid_queue, "get_job_run_status", run_status)

    deid_queue.drain_once()

    assert polls["n"] == 3, "gave up too early or waited past the threshold"
