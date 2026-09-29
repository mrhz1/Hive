import os
import re
import threading
import time

# Patient codes are not ours to invent. The sending system puts one in the
# path or the file name, and the same code means the same person
# everywhere -- so a patient is created *with* its code rather than being
# handed a generated one.
#
# Two to four letters, then three or four digits: AA0001, AA1200, AVDD001,
# AVDD1200. The tightness is the point. Nothing can check a candidate
# against the patient table (patients do not exist until their files have
# been redacted), so this pattern is the only thing between a real code and
# a folder called REPORT -- which a looser `[A-Z0-9]{6}` would have
# accepted, along with SCAN01 and IMAGE1.
DEFAULT_PATIENT_CODE_PATTERN = r"[A-Z]{2,4}[0-9]{3,4}"

SERIAL_DIGITS = 16

MAX_SEQUENCE = 999

_serial_lock = threading.Lock()
_last_millis = 0
_sequence = 0


def patient_code_pattern() -> str:
    """Read per call, so a deployment can widen it without a restart."""
    return os.environ.get("PATIENT_CODE_PATTERN", DEFAULT_PATIENT_CODE_PATTERN)


def normalise_patient_code(value):
    """Trim and upper-case a candidate; anything else is passed through.

    Codes arrive from file names typed by other systems, so `aa1234` and
    `AA1234 ` are the same patient.
    """
    if not isinstance(value, str):
        return value
    return value.strip().upper()


def is_patient_code(value) -> bool:
    if not isinstance(value, str) or not value:
        return False
    # fullmatch, so a trailing newline or a stray character cannot ride
    # along on a pattern whose author forgot to anchor it.
    return re.fullmatch(patient_code_pattern(), value) is not None


def new_document_serial() -> str:
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
