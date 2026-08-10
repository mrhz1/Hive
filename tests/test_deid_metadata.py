"""What de-identification records about its own output."""
import pathlib

from app import deid
from conftest import minimal_patient


def _file_with_patient(client, name="scan.pdf"):
    patient_id = client.post("/patients", json=minimal_patient()).json()["id"]
    application_id = client.post(
        "/applications", json={"patient_id": patient_id}
    ).json()["id"]
    record = client.post(
        f"/applications/{application_id}/files",
        files=[("files", (name, b"%PDF-1.4 fake", "application/pdf"))],
    ).json()[0]
    return patient_id, record


def test_the_four_facts_are_recorded(as_admin, storage_root):
    """A redacted document answers none of these on its own: what it is called, when it was redacted, whose it is, and what format it is."""
    patient_id, record = _file_with_patient(as_admin)

    class Row:
        id = record["id"]
        application_id = record["application_id"]

    deid._record_deid_metadata(Row(), pathlib.Path("/out/A7K2P9-pdf-1_deid.pdf"))

    metadata = as_admin.get(f"/files/{record['id']}/metadata").json()["metadata"]

    assert metadata["deidentified_file_name"] == "A7K2P9-pdf-1_deid.pdf"
    assert metadata["patient_id"] == patient_id
    assert metadata["deidentified_file_type"] == "pdf"
    assert metadata["deidentified_at"].startswith("20")


def test_the_original_metadata_survives_the_merge(as_admin, storage_root):
    """Merged into the row that describes the original, not over it."""
    _, record = _file_with_patient(as_admin)

    before = as_admin.get(f"/files/{record['id']}/metadata").json()["metadata"]
    before["hive_test_marker"] = "keep me"

    from app.crud import file_metadata as metadata_crud

    class Row:
        id = record["id"]
        application_id = record["application_id"]

    # Seed a key the extractor would have written, then merge.
    with deid.hive_cursor() as cursor:
        metadata_crud.merge_metadata_for_file(
            cursor, record["id"], {"hive_test_marker": "keep me"}
        )
    deid._record_deid_metadata(Row(), pathlib.Path("/out/x_deid.pdf"))

    after = as_admin.get(f"/files/{record['id']}/metadata").json()["metadata"]
    assert after["hive_test_marker"] == "keep me"
    assert after["deidentified_file_name"] == "x_deid.pdf"


def test_a_dicom_output_records_its_own_type(as_admin, storage_root):
    _, record = _file_with_patient(as_admin, name="study.dcm")

    class Row:
        id = record["id"]
        application_id = record["application_id"]

    deid._record_deid_metadata(Row(), pathlib.Path("/out/study_deid.dcm"))

    metadata = as_admin.get(f"/files/{record['id']}/metadata").json()["metadata"]
    assert metadata["deidentified_file_type"] == "dcm"


def test_a_failure_to_annotate_does_not_raise(as_admin, storage_root, monkeypatch):
    """The redaction already succeeded; losing the annotation must not turn that into a failed run."""

    def boom(*args, **kwargs):
        raise RuntimeError("hive is down")

    monkeypatch.setattr(deid.metadata_crud, "merge_metadata_for_file", boom)
    _, record = _file_with_patient(as_admin)

    class Row:
        id = record["id"]
        application_id = record["application_id"]

    deid._record_deid_metadata(Row(), pathlib.Path("/out/x_deid.pdf"))  # no raise
