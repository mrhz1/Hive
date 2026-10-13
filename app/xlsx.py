from io import BytesIO
from typing import List, Optional, Sequence, Tuple

MIN_WIDTH = 12
MAX_WIDTH = 80


def workbook_bytes(
    headers: List[str],
    rows: List[List[object]],
    sheet_title: str = "Sheet1",
    dictionary: Optional[Sequence[Tuple[str, str]]] = None,
) -> bytes:
    """One sheet of rows; with `dictionary`, a second "Data dictionary"
    sheet saying what each column means (protocol 7.10)."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    book = Workbook()
    sheet = book.active
    sheet.title = "".join(c for c in sheet_title if c not in r"[]:*?/\\")[:31] or "Sheet1"

    sheet.append(list(headers))
    for cell in sheet[1]:
        cell.font = Font(bold=True)

    widths = [len(str(header)) for header in headers]

    for row in rows:
        values = ["" if value is None else str(value) for value in row]
        sheet.append(values)
        for index, value in enumerate(values):
            if index < len(widths):
                widths[index] = max(widths[index], len(value))

    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = max(
            MIN_WIDTH, min(width + 2, MAX_WIDTH)
        )

    sheet.freeze_panes = "A2"

    if dictionary:
        definitions = book.create_sheet("Data dictionary")
        definitions.append(["Column", "Meaning"])
        for cell in definitions[1]:
            cell.font = Font(bold=True)
        for column, meaning in dictionary:
            definitions.append([column, meaning])
        definitions.column_dimensions["A"].width = 24
        definitions.column_dimensions["B"].width = MAX_WIDTH
        definitions.freeze_panes = "A2"

    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()
