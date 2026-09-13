import os
from typing import List

PDF = "pdf"
DICOM = "dicom"
DOCX = "docx"

EXTENSIONS = {
    ".pdf": PDF,
    ".dcm": DICOM,
    ".dicom": DICOM,
    ".doc": DOCX,
    ".docx": DOCX,
}

OUTPUT_EXTENSION = {
    PDF: ".pdf",
    DICOM: ".dcm",
    DOCX: ".docx",
}

RASTER_KINDS = (PDF, DICOM)


def kind_for(path: str) -> str:
    _, extension = os.path.splitext(path)
    return EXTENSIONS.get(extension.lower(), "")


def is_supported(path: str) -> bool:
    return bool(kind_for(path))


def needs_ocr(path: str) -> bool:
    return kind_for(path) in RASTER_KINDS


def output_extension(path: str) -> str:
    return OUTPUT_EXTENSION.get(kind_for(path), ".pdf")


def supported_globs(recursive: bool) -> List[str]:
    prefix = "**/*" if recursive else "*"
    return [f"{prefix}{extension}" for extension in sorted(EXTENSIONS)]



def open_document(path: str):
    kind = kind_for(path)

    if kind == PDF:
        from deid.pdf_io import open_pdf

        return open_pdf(path), kind

    if kind == DICOM:
        from deid.dicom_io import open_dicom

        return open_dicom(path), kind

    raise RuntimeError(f"{path} is not a raster document ({kind or 'unknown'})")


def render_pages(handle, kind: str, dpi: int):
    if kind == PDF:
        from deid.pdf_io import render_pages as render

        return render(handle, dpi)

    if kind == DICOM:
        from deid.dicom_io import render_frames

        return render_frames(handle, dpi)

    raise RuntimeError(f"cannot rasterise a {kind or 'unknown'} document")


def page_count(handle, kind: str) -> int:
    if kind == PDF:
        return handle.page_count

    if kind == DICOM:
        from deid.dicom_io import frames

        return len(frames(handle))

    raise RuntimeError(f"cannot count pages of a {kind or 'unknown'} document")


def apply_redactions(handle, kind: str, page_number: int, boxes, scale: float, fill: str):
    if kind == PDF:
        from deid.pdf_io import apply_redactions as apply

        return apply(handle, page_number, boxes, scale, fill)

    if kind == DICOM:
        from deid.dicom_io import apply_redactions as apply

        return apply(handle, page_number, boxes, scale, fill)

    raise RuntimeError(f"cannot redact a {kind or 'unknown'} document")


_PDF_PHI_KEYS = ("author",)


def _scrub_pdf(handle, redact) -> List[str]:
    from deid.metadata import PLACEHOLDER, deidentify_value

    info = dict(handle.metadata or {})
    touched: List[str] = []

    if redact is None:
        touched = [key for key, value in info.items() if value]
        handle.set_metadata({})
    else:
        updated = dict(info)
        for key, value in info.items():
            if not value or not str(value).strip():
                continue
            replacement = deidentify_value(
                str(value), redact, known_phi=key in _PDF_PHI_KEYS
            )
            if replacement is not None:
                updated[key] = replacement
                touched.append(key)
            elif key in _PDF_PHI_KEYS:
                updated[key] = PLACEHOLDER
                touched.append(key)
        handle.set_metadata(updated)

    try:
        handle.del_xml_metadata()
        touched.append("<xmp>")
    except Exception:  # pragma: no cover - not every PDF has XMP
        pass

    return touched


def scrub_metadata(handle, kind: str, redact=None) -> List[str]:
    if kind == PDF:
        return _scrub_pdf(handle, redact)

    if kind == DICOM:
        from deid.dicom_io import scrub_metadata as scrub

        return scrub(handle, redact)

    if kind == DOCX:
        from deid.docx_io import deidentify_properties

        return deidentify_properties(handle, redact)

    return []


def save_document(handle, kind: str, output_path: str) -> None:
    if kind == PDF:
        from deid.pdf_io import save_pdf

        return save_pdf(handle, output_path)

    if kind == DICOM:
        from deid.dicom_io import save_dicom

        return save_dicom(handle, output_path)

    if kind == DOCX:
        from deid.docx_io import save_docx

        return save_docx(handle, output_path)

    raise RuntimeError(f"cannot save a {kind or 'unknown'} document")


def close_document(handle, kind: str) -> None:
    if kind == PDF:
        handle.close()
