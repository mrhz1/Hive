"""Keeping exported text from turning into spreadsheet formulas.

Excel (and openpyxl, when writing) treats a cell that starts with = + - @
as a formula, so a file name or a PDF title like `=HYPERLINK(...)` would
run when someone opens the export. Such text gets a leading apostrophe,
which Excel shows as plain text. Numbers ("-5", "+1.5") are left alone.

Used for the files people open in Excel (exports, reports, MANIFEST). The
data tables of a workspace or a Zone 2 release are not changed: analysts
read them in R or Python, where the apostrophe would be a wrong value.
"""

import re

_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")
_NUMBER = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")


def cell(value):
    if isinstance(value, str) and value.startswith(_TRIGGERS) and not _NUMBER.match(value):
        return "'" + value
    return value


def row(values):
    return [cell(v) for v in values]
