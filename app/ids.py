import os
import re
import threading
import time

DEFAULT_PATIENT_CODE_PATTERN = r"[A-Z]{2,4}[0-9]{3,4}"

MAX_SEQUENCE = 999

_lock = threading.Lock()
_last_millis = 0
_sequence = 0


FORMAT_ENTRY = re.compile(r"^([A-Z]{1,10}):([0-9]{1,2})$")


def _parse_formats(raw):
    formats = []
    for entry in raw.split(","):
        entry = entry.strip().upper()
        if not entry:
            continue
        match = FORMAT_ENTRY.match(entry)
        if not match or not 1 <= int(match.group(2)) <= 10:
            raise ValueError(
                f"PATIENT_CODE_FORMATS: '{entry}' is not PREFIX:DIGITS "
                "(letters, a colon, 1 to 10), e.g. AA:4,BBCDE:4"
            )
        formats.append((match.group(1), int(match.group(2))))
    return formats


def code_formats():
    """The allowed formats from PATIENT_CODE_FORMATS, e.g. AA:4,BBCDE:4.

    Each is a fixed prefix and an exact number of digits. Empty when unset,
    and PATIENT_CODE_PATTERN (or the default) applies instead.
    """
    return _parse_formats(os.environ.get("PATIENT_CODE_FORMATS", ""))


def describe_code_formats():
    return ", ".join(
        f"{prefix} + {digits} digits (e.g. {prefix}{'1'.rjust(digits, '0')})"
        for prefix, digits in code_formats()
    )


def patient_code_pattern():
    formats = code_formats()
    if formats:
        return "(?:" + "|".join(f"{p}[0-9]{{{d}}}" for p, d in formats) + ")"
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
