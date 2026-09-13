import logging
from typing import Callable, Iterator, List, Tuple

log = logging.getLogger(__name__)

CLEARED_PROPERTIES = (
    "author",
    "category",
    "comments",
    "content_status",
    "identifier",
    "keywords",
    "language",
    "last_modified_by",
    "subject",
    "title",
    "version",
)


def open_docx(path: str):
    import docx

    try:
        return docx.Document(path)
    except Exception as exc:
        raise RuntimeError(f"Could not open Word document {path}: {exc}") from exc


def _paragraphs_in(container) -> Iterator:
    for paragraph in getattr(container, "paragraphs", []):
        yield paragraph

    for table in getattr(container, "tables", []):
        for row in table.rows:
            for cell in row.cells:
                for paragraph in _paragraphs_in(cell):
                    yield paragraph


def paragraphs(document) -> Iterator:
    yield from _paragraphs_in(document)

    for section in document.sections:
        for part in (section.header, section.footer):
            if part is not None:
                yield from _paragraphs_in(part)


def read_blocks(document) -> List[Tuple[int, str]]:
    return [
        (index, paragraph.text)
        for index, paragraph in enumerate(paragraphs(document))
        if paragraph.text and paragraph.text.strip()
    ]


def replace_paragraph_text(paragraph, text: str) -> None:
    runs = paragraph.runs
    if not runs:
        return

    runs[0].text = text
    for run in runs[1:]:
        run.text = ""


def redact_document(document, redact: Callable[[str], str]) -> int:
    changed = 0

    for paragraph in paragraphs(document):
        original = paragraph.text
        if not original or not original.strip():
            continue

        replacement = redact(original)
        if replacement != original:
            replace_paragraph_text(paragraph, replacement)
            changed += 1

    return changed


AUTHORSHIP_PROPERTIES = ("author", "last_modified_by")

SCANNED_PROPERTIES = CLEARED_PROPERTIES + ("category", "keywords", "subject")


def deidentify_properties(document, redact=None) -> List[str]:
    from deid.metadata import PLACEHOLDER, deidentify_value

    touched: List[str] = []
    properties = document.core_properties

    for name in dict.fromkeys(SCANNED_PROPERTIES + AUTHORSHIP_PROPERTIES):
        try:
            current = getattr(properties, name, None)
        except Exception:  # pragma: no cover - python-docx typing
            continue

        if not current or not str(current).strip():
            continue

        if redact is None:
            setattr(properties, name, "")
            touched.append(name)
            continue

        replacement = deidentify_value(
            str(current), redact, known_phi=name in AUTHORSHIP_PROPERTIES
        )
        if replacement is None:
            continue

        try:
            setattr(properties, name, replacement or PLACEHOLDER)
            touched.append(name)
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("could not rewrite document property %s: %s", name, exc)

    return touched


clear_properties = deidentify_properties


def save_docx(document, output_path: str) -> None:
    try:
        document.save(output_path)
    except Exception as exc:
        raise RuntimeError(
            f"Could not write redacted Word document {output_path}: {exc}"
        ) from exc
