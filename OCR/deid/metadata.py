"""De-identifying a document's metadata, rather than deleting it.

Every format here used to have its metadata *erased*: the PDF info
dictionary emptied, a fixed list of DICOM tags deleted, a fixed list of
Word properties blanked. Safe, but lossy in two directions at once.

It threw away information that is not PHI. `Modality`, `StudyDescription`,
`Manufacturer`, the acquisition parameters -- the things that make a
study worth keeping -- went with the patient name, because the rule was
"this tag is on the list" rather than "this value identifies someone".

And it missed PHI that was not on the list. A name in
`StudyDescription`, a phone number in `ImageComments`, an address typed
into a Word `comments` field: none of those tags are on any deny-list,
and all of them survived into the output.

So metadata now goes through the same analyzer the page content does.
The field stays; its value is de-identified in place, and
`PatientName: Doe^Jane` becomes `PatientName: <PATIENT>` rather than
disappearing.

**The analyzer is not trusted on its own.** It was trained on clinical
prose, and a DICOM PN value (`Doe^Jane^A^^Dr`) or a bare `MRN4471` looks
nothing like prose. A field known to hold PHI is therefore replaced
outright when the analyzer finds nothing in it -- the field is kept, but
never its original value. Detection only ever *adds* to that guarantee;
it cannot weaken it.
"""
import logging
from typing import Callable, Optional

log = logging.getLogger(__name__)

# What a known-PHI field becomes when the analyzer does not fire on it.
PLACEHOLDER = "<REMOVED>"

Redactor = Callable[[str], str]


def deidentify_value(
    value: str, redact: Redactor, known_phi: bool = False
) -> Optional[str]:
    """The de-identified form of one metadata value.

    Returns None when nothing needs to change, so callers can leave the
    field -- and its original formatting -- alone.
    """
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

    # The analyzer found nothing. In a field that is known to carry PHI,
    # that is a miss rather than a clean bill of health.
    return PLACEHOLDER if known_phi else None
