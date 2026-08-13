"""The access trail: who saw what, who was refused, and from where.

`audit_logs` answers "what changed"; none of this is a change, so none of
it was recorded anywhere durable before.
"""
import pytest
from conftest import ADMIN_ID, VIEWER_USER, minimal_patient

from app import access_log


def _file_events(rows, action):
    """Events about an application's documents, and nothing else."""
    return [
        row
        for row in rows
        if row["action"] == action and row["resource_type"] == "application_file"
    ]


def _patient_and_application(client):
    patient_id = client.post("/patients", json=minimal_patient()).json()["id"]
    application_id = client.post(
        "/applications", json={"patient_id": patient_id}
    ).json()["id"]
    return patient_id, application_id


def _upload(client, application_id, name="scan.pdf", data=b"%PDF-1.4 fake"):
    return client.post(
        f"/applications/{application_id}/files",
        files=[("files", (name, data, "application/pdf"))],
    ).json()[0]


# ------------------------------------------------------- reading a file


def test_opening_the_original_is_recorded_as_a_disclosure(
    as_admin, storage_root, access_events
):
    """A read, not a download -- the viewer showed it, nothing was kept."""
    patient_id, application_id = _patient_and_application(as_admin)
    record = _upload(as_admin, application_id)

    as_admin.get(
        f"/files/{record['id']}/content",
        headers={"X-Forwarded-For": "203.0.113.9", "User-Agent": "Firefox/1"},
    )

    rows = access_events.flush()
    assert not _file_events(rows, "download")

    reads = _file_events(rows, "read")
    assert len(reads) == 1

    event = reads[0]
    assert event["actor_id"] == ADMIN_ID
    assert event["actor_username"] == "admin"
    assert event["patient_id"] == patient_id
    assert event["application_id"] == application_id
    assert event["resource_id"] == record["id"]
    assert event["source_ip"] == "203.0.113.9"
    assert event["user_agent"] == "Firefox/1"
    assert event["request_id"]
    assert event["outcome"] == "success"
    # The whole point of the flag.
    assert event["identified"] is True


def test_opening_the_redacted_copy_is_not_a_disclosure(
    as_admin, storage_root, access_events
):
    """Same endpoint, same permission -- only the flag separates a
    routine read from PHI leaving the building."""
    _, application_id = _patient_and_application(as_admin)
    record = _upload(as_admin, application_id)

    # Inside the storage root, or resolve_stored_path refuses it.
    redacted = storage_root / "redacted.pdf"
    redacted.parent.mkdir(parents=True, exist_ok=True)
    redacted.write_bytes(b"%PDF-1.4 redacted")
    as_admin.put(
        f"/files/{record['id']}",
        json={"deid_status": "done", "de_identified_file_path": str(redacted)},
    )

    as_admin.get(f"/files/{record['id']}/content", params={"deidentified": True})

    assert _file_events(access_events.flush(), "read")[-1]["identified"] is False


def test_taking_a_copy_away_is_recorded_as_a_download(
    as_admin, storage_root, access_events
):
    """The same bytes as a read, but a copy of them now exists somewhere
    this system cannot see -- which is the distinction the trail is for."""
    _, application_id = _patient_and_application(as_admin)
    record = _upload(as_admin, application_id)

    response = as_admin.get(
        f"/files/{record['id']}/content", params={"download": True}
    )

    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith("attachment")

    rows = access_events.flush()
    assert not _file_events(rows, "read")

    downloads = _file_events(rows, "download")
    assert len(downloads) == 1
    assert downloads[0]["identified"] is True
    assert downloads[0]["byte_count"] == record["file_size"]


def test_a_viewer_may_read_a_file_but_not_download_it(
    as_admin, client, storage_root, access_events
):
    """`application:view` opens it in the viewer; keeping a copy is
    `files:download`, and the viewer hides its Download button to match."""
    _, application_id = _patient_and_application(as_admin)
    record = _upload(as_admin, application_id)

    client.headers.update({"REMOTE-USER": VIEWER_USER})

    assert client.get(f"/files/{record['id']}/content").status_code == 200

    denied = client.get(f"/files/{record['id']}/content", params={"download": True})
    assert denied.status_code == 403
    assert "files:download" in denied.json()["error"]["detail"]

    rows = access_events.flush()
    assert not _file_events(rows, "download")
    assert [r["resource_id"] for r in rows if r["action"] == "denied"] == [
        "files:download"
    ]


def test_the_event_is_partitioned_by_the_day_it_happened(
    as_admin, storage_root, access_events
):
    """A year of this is the one table queried by date."""
    _, application_id = _patient_and_application(as_admin)
    record = _upload(as_admin, application_id)

    as_admin.get(f"/files/{record['id']}/content")

    event = _file_events(access_events.flush(), "read")[0]
    assert event["event_date"] == event["occurred_at"].strftime("%Y-%m-%d")


def test_a_file_that_is_missing_is_not_recorded_as_read(
    as_admin, storage_root, access_events
):
    """The record says what was served, not what was asked for."""
    _, application_id = _patient_and_application(as_admin)
    record = _upload(as_admin, application_id)

    as_admin.put(
        f"/files/{record['id']}",
        json={"de_identified_file_path": "/nowhere/gone.pdf"},
    )
    as_admin.get(f"/files/{record['id']}/content", params={"deidentified": True})

    assert not _file_events(access_events.flush(), "read")


# ------------------------------------------------------------- the bulk path


def test_an_export_records_how_much_left(as_admin, storage_root, access_events):
    """One click, the whole table. This is the exfiltration path."""
    _, application_id = _patient_and_application(as_admin)
    _upload(as_admin, application_id, name="a.pdf")
    _upload(as_admin, application_id, name="b.pdf")

    as_admin.get("/file-metadata/export", params={"search": ""})

    exports = [r for r in access_events.flush() if r["action"] == "export"]
    assert len(exports) == 1
    assert exports[0]["record_count"] == 2
    assert exports[0]["identified"] is True
    assert exports[0]["resource_type"] == "file_metadata"


def test_browsing_the_metadata_records_the_search(
    as_admin, storage_root, access_events
):
    _, application_id = _patient_and_application(as_admin)
    _upload(as_admin, application_id)

    as_admin.get("/file-metadata", params={"search": "siemens"})

    reads = [
        r
        for r in access_events.flush()
        if r["action"] == "read" and r["resource_type"] == "file_metadata"
    ]
    assert "siemens" in reads[-1]["detail"]


def test_reading_a_patient_is_recorded(as_admin, access_events):
    patient_id = as_admin.post("/patients", json=minimal_patient()).json()["id"]

    as_admin.get(f"/patients/{patient_id}")

    reads = [
        r
        for r in access_events.flush()
        if r["action"] == "read" and r["resource_type"] == "patient"
    ]
    assert reads[-1]["patient_id"] == patient_id
    assert reads[-1]["identified"] is True


def test_listing_patients_is_not_recorded(as_admin, access_events):
    """Hit on every page load; recording it would bury the reads that
    mean something."""
    as_admin.post("/patients", json=minimal_patient())

    as_admin.get("/patients")

    assert not [
        r
        for r in access_events.flush()
        if r["action"] == "read" and r["resource_type"] == "patient"
    ]


# --------------------------------------------------------- refusals


def test_a_permission_denial_is_recorded(client, access_events):
    client.headers.update({"REMOTE-USER": "nobody"})

    client.get("/patients")

    denials = [r for r in access_events.flush() if r["action"] == "denied"]
    assert denials[-1]["outcome"] == "denied"
    assert denials[-1]["resource_id"] == "patient:view"
    assert denials[-1]["actor_username"] == "nobody"


def test_an_unknown_user_is_recorded(client, access_events):
    client.headers.update({"REMOTE-USER": "mallory"})

    client.get("/patients")

    failures = [r for r in access_events.flush() if r["action"] == "auth_failure"]
    assert failures[-1]["actor_username"] == "mallory"
    assert failures[-1]["detail"] == "unknown user"


def test_a_missing_identity_header_is_recorded(client, access_events):
    client.get("/patients")

    failures = [r for r in access_events.flush() if r["action"] == "auth_failure"]
    assert "REMOTE-USER" in failures[-1]["detail"]


# ------------------------------------------------------------ the writer


def test_a_batch_is_one_statement_per_day(as_admin, storage_root, access_events, cursor):
    """The cost of a Hive INSERT is per statement, not per row -- which
    is the entire reason for buffering."""
    _, application_id = _patient_and_application(as_admin)
    record = _upload(as_admin, application_id)

    for _ in range(5):
        as_admin.get(f"/files/{record['id']}/content")

    before = len(cursor.statements)
    access_events.flush()
    inserts = [
        sql
        for sql, _ in cursor.statements[before:]
        if sql.startswith("INSERT INTO TABLE `access_logs`")
    ]

    assert len(inserts) == 1, "one day of events should be one INSERT"
    assert len(_file_events(access_events.rows, "read")) == 5


def test_a_write_failure_does_not_raise(as_admin, storage_root, access_events, monkeypatch):
    """The trail failing must not take a request with it."""
    _, application_id = _patient_and_application(as_admin)
    record = _upload(as_admin, application_id)
    as_admin.get(f"/files/{record['id']}/content")

    def explode(_batch):
        raise RuntimeError("hive is down")

    monkeypatch.setattr(access_log, "_write", explode)

    assert access_log.flush_once() == 0  # logged, not raised


def test_the_queue_is_bounded(monkeypatch):
    """Dropping is better than growing until the process dies of it."""
    monkeypatch.setattr(access_log, "_ensure_writer", lambda: None)

    for _ in range(access_log.MAX_QUEUED + 5):
        access_log._enqueue({"id": "x"})

    assert access_log._queue.qsize() <= access_log.MAX_QUEUED

    while True:
        try:
            access_log._queue.get_nowait()
        except Exception:
            break


@pytest.mark.parametrize("disabled", ["0", "false", "no", "off"])
def test_it_can_be_switched_off(disabled, monkeypatch):
    monkeypatch.setenv("ACCESS_LOG_ENABLED", disabled)
    import importlib

    reloaded = importlib.reload(access_log)
    try:
        assert reloaded.ENABLED is False
    finally:
        monkeypatch.delenv("ACCESS_LOG_ENABLED", raising=False)
        importlib.reload(access_log)
