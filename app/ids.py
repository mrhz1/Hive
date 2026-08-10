"""Application-generated identifiers."""
import secrets
import threading
import time

PATIENT_ID_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
PATIENT_ID_LENGTH = 6

PATIENT_ID_ATTEMPTS = 10

SERIAL_DIGITS = 16

MAX_SEQUENCE = 999

_serial_lock = threading.Lock()
_last_millis = 0
_sequence = 0


def random_patient_id() -> str:
    """One candidate id. Callers must check it is free."""
    return "".join(
        secrets.choice(PATIENT_ID_ALPHABET) for _ in range(PATIENT_ID_LENGTH)
    )


def new_patient_id(is_taken) -> str:
    """A patient id that is free, per the `is_taken(candidate)` predicate."""
    for _ in range(PATIENT_ID_ATTEMPTS):
        candidate = random_patient_id()
        if not is_taken(candidate):
            return candidate
    raise RuntimeError(
        f"Could not find a free {PATIENT_ID_LENGTH}-character patient id in "
        f"{PATIENT_ID_ATTEMPTS} attempts; the id space is saturated"
    )


def new_document_serial() -> str:
    """A 16-digit serial: 13 digits of epoch milliseconds, 3 of counter."""
    global _last_millis, _sequence

    with _serial_lock:
        while True:
            millis = max(int(time.time() * 1000), _last_millis)

            if millis > _last_millis:
                _last_millis = millis
                _sequence = 0
                break

            if _sequence < MAX_SEQUENCE:
                _sequence += 1
                break

            time.sleep(0.0005)

        return f"{_last_millis:013d}{_sequence:03d}"
