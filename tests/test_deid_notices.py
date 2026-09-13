import contextlib
from datetime import datetime

import pytest
from conftest import ADMIN_ID, VIEWER_ID, minimal_patient

from app import deid_notices


class Row:

    def __init__(self, file_id, created_at, status, name=None, output=None):
        self.id = file_id
        self.application_id = "app-1"
        self.created_at = datetime(2026, 7, 1, 12, created_at)
        self.deid_status = status
        self.sanitized_file_name = name or f"{file_id}.pdf"
        self.deidentified_file_name = output


class Person:

    def __init__(self, user_id, email):
        self.id = user_id
        self.email = email
        self.username = user_id
        self.first_name = "Dana"
        self.last_name = "Reid"


ASSIGNEE = Person("user-assignee", "assignee@example.com")
CREATOR = Person("user-creator", "creator@example.com")


class Table(dict):
    """The file rows, plus who the notice should reach and what was sent."""

    recipients = None
    outbox = None


@pytest.fixture
def table(monkeypatch, tmp_path, sent_emails):
    rows = Table()
    recipients = [ASSIGNEE]

    monkeypatch.setattr("app.storage.STORAGE_ROOT", tmp_path / "patient_files")
    monkeypatch.setattr(
        deid_notices, "hive_cursor", lambda: contextlib.nullcontext(None)
    )
    monkeypatch.setattr(
        deid_notices.crud,
        "list_files",
        lambda _cursor, application_id=None: list(rows.values()),
    )
    monkeypatch.setattr(
        deid_notices, "upload_recipients", lambda *a, **kw: list(recipients)
    )
    monkeypatch.setattr(
        deid_notices, "source_folder_for", lambda *a, **kw: "/data/intake"
    )

    rows.recipients = recipients
    rows.outbox = sent_emails
    return rows


def test_nothing_is_sent_while_another_file_is_still_running(table):
    table["a"] = Row("a", 1, "done")
    table["b"] = Row("b", 2, "processing")

    assert deid_notices.notify_if_finished("app-1") is False
    assert table.outbox == []


def test_a_queued_file_also_holds_the_notice_back(table):
    table["a"] = Row("a", 1, "done")
    table["b"] = Row("b", 2, "queued")

    assert deid_notices.notify_if_finished("app-1") is False
    assert table.outbox == []


def test_one_notice_once_the_last_file_settles(table):
    table["a"] = Row("a", 1, "done", output="a_deid.pdf")
    table["b"] = Row("b", 2, "done", output="b_deid.pdf")

    assert deid_notices.notify_if_finished("app-1") is True

    assert len(table.outbox) == 1
    mail = table.outbox[0]
    assert mail["to"] == ["assignee@example.com"]
    assert mail["subject"] == "De-identification complete -- 2 file(s) ready"
    assert "All 2 document(s) have been de-identified" in mail["body"]
    assert "a_deid.pdf" in mail["body"]
    assert "b_deid.pdf" in mail["body"]
    assert "Uploaded from: /data/intake" in mail["body"]


def test_a_ten_file_batch_sends_exactly_one_notice(table):
    for n in range(10):
        table[f"f{n}"] = Row(f"f{n}", n, "processing")

    sent = 0
    for n in range(10):
        table[f"f{n}"].deid_status = "done"
        if deid_notices.notify_if_finished("app-1"):
            sent += 1

    assert sent == 1, "the batch should be announced once, not per file"
    assert len(table.outbox) == 1
    assert table.outbox[0]["subject"] == "De-identification complete -- 10 file(s) ready"


def test_a_partial_failure_names_the_documents_that_did_not_make_it(table):
    table["a"] = Row("a", 1, "done", output="a_deid.pdf")
    table["b"] = Row("b", 2, "failed", name="broken.pdf")

    assert deid_notices.notify_if_finished("app-1") is True

    mail = table.outbox[0]
    assert mail["subject"] == "De-identification partly failed -- 1 of 2 files"
    assert "1 of 2 document(s) were de-identified; 1 could not be." in mail["body"]
    assert "These documents were not de-identified:" in mail["body"]
    assert "broken.pdf" in mail["body"]


def test_a_total_failure_says_the_run_needs_retrying(table):
    table["a"] = Row("a", 1, "failed")

    assert deid_notices.notify_if_finished("app-1") is True

    mail = table.outbox[0]
    assert mail["subject"] == "De-identification failed -- application app-1"
    assert "needs to be retried" in mail["body"]


def test_pending_files_are_not_a_batch(table):
    table["a"] = Row("a", 1, "pending")

    assert deid_notices.notify_if_finished("app-1") is False
    assert table.outbox == []


def test_a_second_run_finishing_at_once_does_not_send_twice(table):
    table["a"] = Row("a", 1, "done")

    assert deid_notices.notify_if_finished("app-1") is True
    assert deid_notices.notify_if_finished("app-1") is False
    assert len(table.outbox) == 1


def test_a_later_re_run_of_the_same_file_is_announced_again(table, monkeypatch):
    table["a"] = Row("a", 1, "done")

    assert deid_notices.notify_if_finished("app-1") is True

    monkeypatch.setattr(deid_notices, "REPEAT_AFTER_SECONDS", 0)
    assert deid_notices.notify_if_finished("app-1") is True
    assert len(table.outbox) == 2


def test_a_changed_outcome_is_always_announced(table):
    table["a"] = Row("a", 1, "done")
    assert deid_notices.notify_if_finished("app-1") is True

    table["b"] = Row("b", 2, "failed")
    assert deid_notices.notify_if_finished("app-1") is True

    assert [mail["subject"] for mail in table.outbox] == [
        "De-identification complete -- 1 file(s) ready",
        "De-identification partly failed -- 1 of 2 files",
    ]


def test_it_falls_back_to_the_creator_when_nobody_is_assigned(table):
    table.recipients[:] = [CREATOR]
    table["a"] = Row("a", 1, "done")

    assert deid_notices.notify_if_finished("app-1") is True
    assert table.outbox[0]["to"] == ["creator@example.com"]


def test_no_recipient_means_no_notice(table):
    table.recipients[:] = []
    table["a"] = Row("a", 1, "done")

    assert deid_notices.notify_if_finished("app-1") is False
    assert table.outbox == []


def test_an_unreadable_table_does_not_take_the_run_down(table, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("hive is away")

    monkeypatch.setattr(deid_notices.crud, "list_files", boom)

    assert deid_notices.notify_if_finished("app-1") is False


def _patient_and_application(client, assigned_to_id=None):
    patient_id = client.post("/patients", json=minimal_patient()).json()["id"]
    payload = {"patient_id": patient_id}
    if assigned_to_id is not None:
        payload["assigned_to_id"] = assigned_to_id
    application_id = client.post("/applications", json=payload).json()["id"]
    return patient_id, application_id


def _upload(client, application_id, name="scan.pdf"):
    return client.post(
        f"/applications/{application_id}/files",
        files=[("files", (name, b"%PDF-1.4 fake", "application/pdf"))],
    ).json()[0]


def _deid_mail(outbox):
    return [mail for mail in outbox if "De-identification" in mail["subject"]]


@pytest.fixture
def fake_pipeline(monkeypatch):
    def produce(source, output_dir, file_id=""):
        output_dir.mkdir(parents=True, exist_ok=True)
        produced = output_dir / f"{source.stem}_deid.pdf"
        produced.write_bytes(b"redacted")
        return produced

    monkeypatch.setattr("app.deid._run_pipeline", produce)
    monkeypatch.setattr("app.deid._record_deid_metadata", lambda *a, **kw: None)


def test_de_identifying_every_file_sends_one_email_at_the_end(
    as_admin, storage_root, sent_emails, fake_pipeline
):
    _, application_id = _patient_and_application(as_admin, assigned_to_id=VIEWER_ID)
    _upload(as_admin, application_id, name="one.pdf")
    _upload(as_admin, application_id, name="two.pdf")

    response = as_admin.post(f"/applications/{application_id}/files/deidentify-all")
    assert response.status_code == 200, response.text

    mail = _deid_mail(sent_emails)
    assert len(mail) == 1, [m["subject"] for m in mail]
    assert mail[0]["to"] == ["viewer@example.com"]
    assert mail[0]["subject"] == "De-identification complete -- 2 file(s) ready"
    assert application_id in mail[0]["body"]


def test_de_identifying_a_single_file_emails_when_it_lands(
    as_admin, storage_root, sent_emails, fake_pipeline
):
    _, application_id = _patient_and_application(as_admin, assigned_to_id=ADMIN_ID)
    record = _upload(as_admin, application_id)

    assert as_admin.post(f"/files/{record['id']}/deidentify").status_code == 200

    mail = _deid_mail(sent_emails)
    assert len(mail) == 1
    assert mail[0]["to"] == ["admin@example.com"]


def test_a_failed_run_is_reported_too(
    as_admin, storage_root, sent_emails, monkeypatch
):
    from app.deid import DeidError

    def explode(*a, **kw):
        raise DeidError("the models were not staged")

    monkeypatch.setattr("app.deid._run_pipeline", explode)

    _, application_id = _patient_and_application(as_admin, assigned_to_id=ADMIN_ID)
    record = _upload(as_admin, application_id)

    as_admin.post(f"/files/{record['id']}/deidentify")

    mail = _deid_mail(sent_emails)
    assert len(mail) == 1
    assert mail[0]["subject"].startswith("De-identification failed")
