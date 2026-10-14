import logging
import os
from typing import List

log = logging.getLogger(__name__)

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

    raise RuntimeError(f"cannot rasterize a {kind or 'unknown'} document")


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

_XMP_PHI_NAMES = frozenset({"creator", "author", "owner", "lastmodifiedby", "authorsposition"})


def _scrub_xmp(xml: str, redact) -> tuple:
    import re
    import xml.etree.ElementTree as ET

    from deid.metadata import PLACEHOLDER, deidentify_value

    for prefix, uri in re.findall(r'xmlns:([\w.-]+)="([^"]+)"', xml):
        try:
            ET.register_namespace(prefix, uri)
        except ValueError:
            pass
    head = xml[: xml.find("<x:xmpmeta")] if "<x:xmpmeta" in xml else ""
    body = xml[len(head):]
    end = body.rfind("</x:xmpmeta>")
    tail = body[end + len("</x:xmpmeta>"):] if end >= 0 else ""
    body = body[: end + len("</x:xmpmeta>")] if end >= 0 else body
    root = ET.fromstring(body)

    touched = []

    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1].lower()

    def clean(value: str, name: str, inherited: bool) -> str:
        known = inherited or name in _XMP_PHI_NAMES
        replacement = deidentify_value(value, redact, known_phi=known)
        if replacement is None:
            return value
        touched.append(name)
        return replacement or PLACEHOLDER

    def walk(element, inherited: bool) -> None:
        name = local(element.tag)
        known = inherited or name in _XMP_PHI_NAMES
        if element.text and element.text.strip():
            element.text = clean(element.text, name, known)
        for key, value in list(element.attrib.items()):
            if key.startswith("{http://www.w3.org/2000/xmlns/}") or not value.strip():
                continue
            if local(key) in ("about", "parsetype", "lang"):
                continue
            element.attrib[key] = clean(value, local(key), False)
        for child in element:
            walk(child, known)

    walk(root, False)
    return head + ET.tostring(root, encoding="unicode") + tail, sorted(set(touched))


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
        xml = handle.get_xml_metadata() if redact is not None else ""
        if xml and xml.strip():
            cleaned, names = _scrub_xmp(xml, redact)
            handle.set_xml_metadata(cleaned)
            touched += [f"xmp:{name}" for name in names]
        else:
            handle.del_xml_metadata()
            touched.append("<xmp>")
    except Exception as exc:
        log.warning("XMP could not be de-identified, removing it: %s", exc)
        try:
            handle.del_xml_metadata()
            touched.append("<xmp>")
        except Exception:
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
