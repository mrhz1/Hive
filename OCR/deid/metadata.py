import logging
from typing import Callable, Optional

log = logging.getLogger(__name__)

PLACEHOLDER = "<REMOVED>"

Redactor = Callable[[str], str]


def deidentify_value(
    value: str, redact: Redactor, known_phi: bool = False
) -> Optional[str]:
    text = "" if value is None else str(value)
    if not text.strip():
        return None

    try:
        cleaned = redact(text)
    except Exception as exc:  # pragma: no cover - one field must not stop the pass
        log.warning("metadata de-identification failed for a value: %s", exc)
        return PLACEHOLDER if known_phi else None

    if cleaned != text:
        return cleaned

    return PLACEHOLDER if known_phi else None
