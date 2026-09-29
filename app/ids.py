import os
import re
import threading
import time

DEFAULT_PATIENT_CODE_PATTERN = r"[A-Z]{2,4}[0-9]{3,4}"

MAX_SEQUENCE = 999

_lock = threading.Lock()
_last_millis = 0
_sequence = 0


def patient_code_pattern():
    return os.environ.get("PATIENT_CODE_PATTERN", DEFAULT_PATIENT_CODE_PATTERN)


def clean_patient_code(value):
    if isinstance(value, str):
        return value.strip().upper()
    return value


def is_patient_code(value):
    if not isinstance(value, str) or not value:
        return False
    return re.fullmatch(patient_code_pattern(), value) is not None


def new_document_serial():
    global _last_millis, _sequence

    with _lock:
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
