import os
from pathlib import Path

from app.logging_setup import get_logger, ref

log = get_logger(__name__)

STAMP_X = float(os.environ.get("DEID_STAMP_X", "36"))
STAMP_Y = float(os.environ.get("DEID_STAMP_Y", "36"))
STAMP_SIZE = float(os.environ.get("DEID_STAMP_FONT_SIZE", "11"))

STAMP_FONT = "helv"


class StampError(Exception):
    pass


def stamp_pdf(path, patient_id: str) -> int:
    """path: local Path or StoragePath; a stored PDF is stamped in a temporary
    copy and uploaded back."""
    from app.blobstore import editable_file

    if not patient_id:
        raise StampError("No patient id to stamp")
    with editable_file(path) as local:
        pages = _stamp_local(local, patient_id)
    log.info("pdf_stamped", file_ref=ref(path), patient_id=patient_id, pages=pages)
    return pages


def _stamp_local(path: Path, patient_id: str) -> int:
    import fitz

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
    return pages
