"""Stamp the patient id onto every page of a de-identified PDF."""
import os
from pathlib import Path

from app.logging_setup import get_logger

log = get_logger(__name__)

STAMP_X = float(os.environ.get("DEID_STAMP_X", "36"))
STAMP_Y = float(os.environ.get("DEID_STAMP_Y", "36"))
STAMP_SIZE = float(os.environ.get("DEID_STAMP_FONT_SIZE", "11"))

STAMP_FONT = "helv"


class StampError(Exception):
    """Raised so the caller can record a failure against the file."""


def stamp_pdf(path: Path, patient_id: str) -> int:
    """Draw `patient_id` at the top-left of every page."""
    import fitz

    if not patient_id:
        raise StampError("No patient id to stamp")

    try:
        document = fitz.open(str(path))
    except Exception as exc:
        raise StampError(f"Could not open {path.name} to stamp it: {exc}") from exc

    temporary = path.with_name(path.name + ".stamping")

    try:
        for page in document:
            page.insert_text(
                fitz.Point(STAMP_X, STAMP_Y + STAMP_SIZE),
                patient_id,
                fontname=STAMP_FONT,
                fontsize=STAMP_SIZE,
                color=(0, 0, 0),
            )

        pages = document.page_count
        document.save(str(temporary), garbage=3, deflate=True)
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        raise StampError(f"Could not stamp {path.name}: {exc}") from exc
    finally:
        document.close()

    os.replace(temporary, path)
    log.info("pdf_stamped", path=str(path), patient_id=patient_id, pages=pages)
    return pages
