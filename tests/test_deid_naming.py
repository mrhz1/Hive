import pathlib
import re
import subprocess
from datetime import datetime, timezone

import pytest
from conftest import minimal_patient

from app import deid, storage

REDACTED = re.compile(r"^(?P<code>[A-Z0-9]{6})-(?P<type>[a-z0-9]+)-(?P<day>\d{8})-(?P<serial>\d{16})_deid\.(?P<ext>[a-z0-9]+)$")

SIDECARS = (".txt", ".report.json")


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


@pytest.fixture
def deid_dirs(tmp_path, monkeypatch):
    pdf = tmp_path / "final" / "pdf"
    monkeypatch.setattr(storage, "DEID_PDF_DIR", pdf)
    monkeypatch.setattr(storage, "DEID_DIRS", {"pdf": pdf})
    return {"pdf": pdf}


@pytest.fixture
def fake_pipeline(monkeypatch):
    """Write what the real OCR run writes: the copy, the text and the report."""

    def fake_run(command, **_kwargs):
        source = pathlib.Path(command[command.index("--input") + 1])
        output_dir = pathlib.Path(command[command.index("--output-dir") + 1])
        suffix = command[command.index("--suffix") + 1]

        output_dir.mkdir(parents=True, exist_ok=True)
        stem = f"{source.stem}{suffix}"
        for extension in (source.suffix, *SIDECARS):
            (output_dir / f"{stem}{extension}").write_bytes(b"redacted")

        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("app.deid.subprocess.run", fake_run)
    monkeypatch.setattr("app.deid._record_deid_metadata", lambda *a, **kw: None)


@pytest.mark.parametrize(
    "extension,document_type",
    [("pdf", "pdf"), ("dcm", "dicom"), ("dicom", "dicom"), ("doc", "word"), ("docx", "word")],
)
def test_the_name_carries_the_patient_code_and_document_type(extension, document_type):
    name = deid.deid_output_name("AB12CD", extension)

    match = REDACTED.match(name)
    assert match, name
    assert match.group("code") == "AB12CD"
    assert match.group("type") == document_type
    assert match.group("day") == _today()
    assert match.group("ext") == extension


def test_every_name_gets_its_own_serial():
    names = {deid.deid_output_name("AB12CD", "pdf") for _ in range(50)}
    assert len(names) == 50, "two runs were handed the same serial"


def test_a_patient_without_a_code_is_still_named():
    assert deid.deid_output_name("", "pdf").startswith("unknown-pdf-")


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


def _deidentify(client, storage_root):
    patient_id, application_id = _patient_and_application(client)
    record = _upload(client, application_id)
    assert client.post(f"/files/{record['id']}/deidentify").status_code == 200

    # The response is built before the background run, so read the row back.
    return patient_id, record, client.get(f"/files/{record['id']}").json()


def test_the_redacted_copy_is_named_for_its_own_run(
    as_admin, storage_root, fake_pipeline
):
    patient_id, record, updated = _deidentify(as_admin, storage_root)

    assert updated["deid_status"] == "done"

    name = updated["deidentified_file_name"]
    match = REDACTED.match(name)
    assert match, name
    assert match.group("code") == patient_id
    assert match.group("type") == "pdf"
    assert match.group("day") == _today()

    assert pathlib.Path(updated["de_identified_file_path"]).name == name
    assert pathlib.Path(updated["de_identified_file_path"]).is_file()


def test_the_copy_does_not_inherit_the_original_s_serial(
    as_admin, storage_root, fake_pipeline
):
    _, record, updated = _deidentify(as_admin, storage_root)

    source_stem = pathlib.Path(record["file_path"]).stem
    source_serial = source_stem.rsplit("-", 1)[-1]
    redacted_serial = REDACTED.match(updated["deidentified_file_name"]).group("serial")

    assert redacted_serial != source_serial
    assert source_stem not in updated["deidentified_file_name"]


def test_the_text_and_the_report_are_renamed_with_the_copy(
    as_admin, storage_root, fake_pipeline
):
    _, record, updated = _deidentify(as_admin, storage_root)

    output_dir = pathlib.Path(record["file_path"]).parent / "deidentified"
    stem = pathlib.Path(updated["deidentified_file_name"]).stem

    assert {path.name for path in output_dir.iterdir()} == {
        f"{stem}.pdf",
        f"{stem}.txt",
        f"{stem}.report.json",
    }


def test_deleting_the_file_still_finds_the_renamed_outputs(
    as_admin, storage_root, fake_pipeline
):
    _, record, _ = _deidentify(as_admin, storage_root)
    output_dir = pathlib.Path(record["file_path"]).parent / "deidentified"

    assert as_admin.delete(f"/files/{record['id']}").status_code == 204

    assert not output_dir.exists() or list(output_dir.iterdir()) == []


def test_a_re_run_names_the_copy_again(as_admin, storage_root, fake_pipeline):
    _, record, first = _deidentify(as_admin, storage_root)

    as_admin.post(f"/files/{record['id']}/deidentify")
    second = as_admin.get(f"/files/{record['id']}").json()

    assert second["deidentified_file_name"] != first["deidentified_file_name"]
    assert REDACTED.match(second["deidentified_file_name"])


def test_a_manually_redacted_upload_uses_the_same_scheme(
    as_admin, storage_root, deid_dirs
):
    patient_id, _ = _patient_and_application(as_admin)

    row = as_admin.post(
        "/files-library",
        data={"patient_id": patient_id},
        files=[("file", ("manual.pdf", b"%PDF-1.4 redacted", "application/pdf"))],
    ).json()

    match = REDACTED.match(row["name"])
    assert match, row["name"]
    assert match.group("code") == patient_id
    assert match.group("type") == "pdf"
