"""A profile of a project's tables, written with the workspace (checklist 10:
data profiling, outlier detection, frequency analysis).

profile.xlsx has three sheets:

- Columns: per table and column, how many values are filled or missing,
  how many distinct, whether it holds numbers, dates or text, and for
  numbers and dates the lowest, highest (and mean) value;
- Frequencies: how often each value occurs, for columns with at most
  MAX_CATEGORIES distinct values that are not identifiers;
- Outliers: numbers outside the usual range (1.5 times the interquartile
  range beyond the quartiles, once a column has MIN_FOR_OUTLIERS values)
  and dates before 1900 or in the future.

It is a starting point for the analyst's exploration (spec 9.2.3), not a
verdict: an outlier can be right.
"""

from collections import Counter
from datetime import date
from pathlib import Path
from statistics import mean, quantiles
from typing import Dict, List, Optional, Tuple

from app.safe_cells import row as safe_row

MAX_CATEGORIES = 50
MIN_FOR_OUTLIERS = 10
EARLIEST = date(1900, 1, 1)


def _number(text: str) -> Optional[float]:
    try:
        return float(text)
    except ValueError:
        return None


def _date(text: str) -> Optional[date]:
    if len(text) < 8:
        return None
    try:
        if len(text) == 8 and text.isdigit():
            return date(int(text[:4]), int(text[4:6]), int(text[6:]))
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _kind(values: List[str]) -> str:
    if values and all(_number(v) is not None for v in values):
        return "number"
    if values and all(_date(v) is not None for v in values):
        return "date"
    return "text"


def _column(table: str, column: str, rows: List[dict]) -> Tuple[list, list, list]:
    values = [str(r.get(column) if r.get(column) is not None else "").strip() for r in rows]
    filled = [v for v in values if v]
    counts = Counter(filled)
    kind = _kind(filled)
    low = high = average = ""
    outliers = []
    key = next(iter(rows[0])) if rows else ""

    if kind == "number" and filled:
        numbers = [_number(v) for v in filled]
        low, high, average = min(numbers), max(numbers), round(mean(numbers), 3)
        if len(numbers) >= MIN_FOR_OUTLIERS:
            q1, _, q3 = quantiles(numbers, n=4)
            spread = q3 - q1
            fence_low, fence_high = q1 - 1.5 * spread, q3 + 1.5 * spread
            for index, row in enumerate(rows, start=2):
                number = _number(str(row.get(column) or "").strip() or "x")
                if number is not None and (number < fence_low or number > fence_high):
                    outliers.append([table, column, index, row.get(key), number,
                                     f"outside {fence_low:g} to {fence_high:g}"])
    elif kind == "date" and filled:
        days = [_date(v) for v in filled]
        low, high = min(days).isoformat(), max(days).isoformat()
        today = date.today()
        for index, row in enumerate(rows, start=2):
            day = _date(str(row.get(column) or "").strip())
            if day and (day < EARLIEST or day > today):
                outliers.append([table, column, index, row.get(key), day.isoformat(),
                                 "before 1900" if day < EARLIEST else "in the future"])

    missing = len(values) - len(filled)
    summary = [table, column, kind, len(values), len(filled), missing,
               round(100 * missing / len(values), 1) if values else 0,
               len(counts), low, high, average]

    frequencies = []
    # every value different (an ID, a file name): nothing to count
    is_identifier = len(counts) == len(filled) and len(filled) > 1
    if counts and len(counts) <= MAX_CATEGORIES and not is_identifier:
        for value, n in counts.most_common():
            frequencies.append([table, column, value, n, round(100 * n / len(values), 1)])
        if missing:
            frequencies.append([table, column, "(missing)", missing,
                                round(100 * missing / len(values), 1)])
    return summary, frequencies, outliers


def write(path: Path, tables: Dict[str, List[dict]]) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    book = Workbook()
    sheets = {
        "Columns": ["table", "column", "kind", "rows", "filled", "missing", "missing %",
                    "distinct", "lowest", "highest", "mean"],
        "Frequencies": ["table", "column", "value", "count", "%"],
        "Outliers": ["table", "column", "row in CSV", "first column", "value", "why"],
    }
    out = {}
    for index, (title, header) in enumerate(sheets.items()):
        sheet = book.active if index == 0 else book.create_sheet()
        sheet.title = title
        sheet.append(header)
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        out[title] = sheet

    for table, rows in tables.items():
        columns = list(dict.fromkeys(k for row in rows for k in row))
        for column in columns:
            summary, frequencies, outliers = _column(table, column, rows)
            out["Columns"].append(safe_row(summary))
            for row in frequencies:
                out["Frequencies"].append(safe_row(row))
            for row in outliers:
                out["Outliers"].append(safe_row(row))

    book.save(str(path))
    return path
