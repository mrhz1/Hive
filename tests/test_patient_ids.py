"""New patients get a 6-character alphanumeric id, not a UUID."""
import re

import pytest

from app.ids import (
    PATIENT_ID_ALPHABET,
    PATIENT_ID_LENGTH,
    new_document_serial,
    new_patient_id,
    random_patient_id,
)
from conftest import minimal_patient

SIX_ALNUM = re.compile(r"^[A-Z0-9]{6}$")


def test_created_patient_gets_a_six_character_id(as_admin):
    created = as_admin.post("/patients", json=minimal_patient()).json()

    assert SIX_ALNUM.match(created["id"]), created["id"]


def test_the_id_is_usable_as_a_key(as_admin):
    """A short id is only worth having if every route still resolves it."""
    created = as_admin.post("/patients", json=minimal_patient()).json()

    fetched = as_admin.get(f"/patients/{created['id']}")

    assert fetched.status_code == 200
    assert fetched.json()["id"] == created["id"]


def test_ids_are_distinct_across_patients(as_admin):
    ids = {
        as_admin.post(
            "/patients", json=minimal_patient(ptemail=f"p{n}@example.com")
        ).json()["id"]
        for n in range(25)
    }

    assert len(ids) == 25


def test_generation_retries_past_a_taken_id():
    taken = {"AAAAAA", "BBBBBB"}
    handed_out = iter(["AAAAAA", "BBBBBB", "C3D4E5"])

    import app.ids as ids

    original = ids.random_patient_id
    ids.random_patient_id = lambda: next(handed_out)
    try:
        assert new_patient_id(lambda c: c in taken) == "C3D4E5"
    finally:
        ids.random_patient_id = original


def test_generation_gives_up_rather_than_looping_forever():
    with pytest.raises(RuntimeError, match="saturated"):
        new_patient_id(lambda candidate: True)


def test_alphabet_and_length():
    for _ in range(200):
        candidate = random_patient_id()
        assert len(candidate) == PATIENT_ID_LENGTH
        assert set(candidate) <= set(PATIENT_ID_ALPHABET)


# ------------------------------------------------------- document serial

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
    """The API hands out serials from request threads, so the generator is only useful if it is safe under concurrency."""
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
