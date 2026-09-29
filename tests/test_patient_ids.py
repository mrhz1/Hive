"""Patient codes and document serials.

Codes are supplied, not generated: the sending system writes one into the
path or the file name, and the same code means the same person everywhere.
Nothing can check a candidate against the patient table -- patients do not
exist until their files have been redacted -- so the pattern carries the
whole weight.
"""

import pytest

from app.ids import (
    DEFAULT_PATIENT_CODE_PATTERN,
    is_patient_code,
    new_document_serial,
    normalise_patient_code,
    patient_code_pattern,
)
from conftest import minimal_patient


@pytest.mark.parametrize(
    "code", ["AA0001", "AA1200", "AVDD001", "AVDD1200", "ABC123", "ZZZZ9999"]
)
def test_real_codes_are_accepted(code):
    assert is_patient_code(code), code


@pytest.mark.parametrize(
    "candidate",
    [
        "REPORT",      # six letters -- the loose pattern would have taken it
        "SCAN01",
        "IMAGE1",
        "CHEST001",    # five letters
        "A0001",       # one letter
        "AVDDD1200",   # five letters
        "AA12",        # two digits
        "AA12345",     # five digits
        "AA1234X",
        "",
        "  ",
    ],
)
def test_things_that_only_look_like_codes_are_refused(candidate):
    assert not is_patient_code(candidate), candidate


def test_a_code_is_matched_whole():
    """A pattern without anchors must not match a prefix.

    `re.match` would accept 'AA1234_scan' here, which is exactly how a
    file name fragment becomes a patient.
    """
    assert not is_patient_code("AA1234_scan")
    assert not is_patient_code("AA1234\n")


def test_codes_are_trimmed_and_upper_cased():
    assert normalise_patient_code(" aa1234 ") == "AA1234"
    assert is_patient_code(normalise_patient_code("avdd1200"))


def test_the_pattern_can_be_widened_without_a_restart(monkeypatch):
    assert not is_patient_code("XX12")

    monkeypatch.setenv("PATIENT_CODE_PATTERN", r"[A-Z]{2}[0-9]{2}")
    assert patient_code_pattern() != DEFAULT_PATIENT_CODE_PATTERN
    assert is_patient_code("XX12")


def test_a_patient_is_created_with_the_code_it_was_given(as_admin):
    created = as_admin.post(
        "/patients", json=minimal_patient(id="AVDD1200")
    ).json()

    assert created["id"] == "AVDD1200"


def test_a_lower_case_code_is_stored_upper_case(as_admin):
    created = as_admin.post("/patients", json=minimal_patient(id="bb0042")).json()

    assert created["id"] == "BB0042"
    assert as_admin.get("/patients/BB0042").status_code == 200


def test_a_patient_cannot_be_created_without_a_code(as_admin):
    payload = minimal_patient()
    del payload["id"]

    response = as_admin.post("/patients", json=payload)

    assert response.status_code == 422


def test_a_code_that_is_not_a_code_is_refused(as_admin):
    response = as_admin.post("/patients", json=minimal_patient(id="REPORT"))

    assert response.status_code == 422
    assert "not a patient code" in response.text


def test_the_same_code_twice_is_a_conflict(as_admin):
    as_admin.post("/patients", json=minimal_patient(id="CC0001"))

    again = as_admin.post(
        "/patients", json=minimal_patient(id="CC0001", ptemail="other@example.com")
    )

    assert again.status_code == 409
    assert "already exists" in again.text


def test_the_code_is_usable_as_a_key(as_admin):
    created = as_admin.post("/patients", json=minimal_patient()).json()

    fetched = as_admin.get(f"/patients/{created['id']}")

    assert fetched.status_code == 200
    assert fetched.json()["id"] == created["id"]


def test_updating_a_patient_cannot_change_its_code(as_admin):
    created = as_admin.post("/patients", json=minimal_patient(id="DD0001")).json()

    as_admin.put(f"/patients/{created['id']}", json={"id": "DD0002", "fstname": "Ann"})

    assert as_admin.get("/patients/DD0002").status_code == 404
    after = as_admin.get("/patients/DD0001").json()
    assert after["fstname"] == "Ann"


def test_serial_is_exactly_sixteen_digits():
    for _ in range(200):
        serial = new_document_serial()
        assert len(serial) == 16, serial
        assert serial.isdigit(), serial


def test_serials_are_strictly_increasing_and_unique():
    serials = [new_document_serial() for _ in range(2000)]

    assert serials == sorted(serials), "serials must sort by upload order"
    assert len(set(serials)) == len(serials), "a serial was reused"


def test_serials_are_unique_across_threads():
    import threading

    produced = []
    lock = threading.Lock()

    def burst():
        mine = [new_document_serial() for _ in range(300)]
        with lock:
            produced.extend(mine)

    threads = [threading.Thread(target=burst) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(set(produced)) == len(produced) == 2400


def test_serial_does_not_go_backwards_when_the_clock_does():
    import app.ids as ids

    first = new_document_serial()

    real_time = ids.time.time
    ids.time = type("t", (), {"time": lambda: real_time() - 60, "sleep": lambda s: None})
    try:
        after_step_back = new_document_serial()
    finally:
        ids.time = __import__("time")

    assert after_step_back > first
