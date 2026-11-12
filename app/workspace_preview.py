"""Read-only preview of a project's Zone 1X workspace (protocol 9.2).

Members of the project with project:workspace can list the workspace and look
at its files in the dashboard: tables (CSV, Excel) a page at a time, PDFs,
images and DICOM. Nothing here writes, renames or deletes, and there is no
download route: corrections go to the source or the cleaning scripts, never
to an exported copy (9.2.3). Every look is written to the access log by the
routes.

Paths come from the browser, so every one is resolved and must stay inside
that project's workspace folder.
"""

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from app.errors import NotFoundError, ValidationError
from app.project_schemas import Project

PAGE_SIZE_MAX = 200
SEARCH_SCAN_MAX = 200_000  # rows looked at when searching one table

TABLE = "table"
PDF = "pdf"
IMAGE = "image"
DICOM = "dicom"
TEXT = "text"
OTHER = "other"

_KINDS = {
    ".csv": TABLE, ".xlsx": TABLE,
    ".pdf": PDF,
    ".png": IMAGE, ".jpg": IMAGE, ".jpeg": IMAGE, ".gif": IMAGE, ".webp": IMAGE,
    ".dcm": DICOM, ".dicom": DICOM,
    ".txt": TEXT, ".md": TEXT, ".log": TEXT, ".json": TEXT,
}
TEXT_LIMIT_BYTES = 512 * 1024


def kind_of(path: Path) -> str:
    return _KINDS.get(path.suffix.lower(), OTHER)


def _expired(project: Project) -> bool:
    value = project.workspace_expires_at
    if not value:
        return False
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return False
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment <= datetime.now(timezone.utc)


def root(project: Project) -> Path:
    if not project.workspace_path:
        raise ValidationError("The project has no workspace; build it first")
    if _expired(project):
        raise ValidationError("The workspace has expired; extend it or build it again")
    from app.blobstore import any_path

    folder = any_path(project.workspace_path).resolve()
    if not folder.is_dir():
        raise ValidationError("The workspace folder is missing; build it again")
    return folder


def list_files(project: Project) -> List[dict]:
    folder = root(project)
    out = []
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        resolved = path.resolve()
        if folder not in resolved.parents:
            continue
        relative = path.relative_to(folder).as_posix()
        out.append({"path": relative, "size": path.stat().st_size, "kind": kind_of(path)})
    return out


def resolve(project: Project, relative: str) -> Path:
    """The file at `relative` inside the workspace, or an error. Refuses
    absolute paths, '..', symlinks and anything that resolves outside."""
    folder = root(project)
    text = (relative or "").replace("\\", "/").strip()
    parts = [p for p in text.split("/") if p]
    if not parts or text.startswith("/") or any(p in (".", "..") for p in parts):
        raise ValidationError("Not a workspace file")
    candidate = folder.joinpath(*parts)
    if candidate.is_symlink():
        raise ValidationError("Not a workspace file")
    resolved = candidate.resolve()
    if folder not in resolved.parents or not resolved.is_file():
        raise NotFoundError("This file is not in the workspace")
    return resolved


def _matches(row: List[str], needle: str) -> bool:
    return any(needle in (cell or "").lower() for cell in row)


def _page(rows_iter, page: int, size: int, needle: str):
    """Slice an iterator of rows into one page, counting matches as it goes."""
    start = (page - 1) * size
    picked, total, scanned = [], 0, 0
    for row in rows_iter:
        scanned += 1
        if needle and scanned > SEARCH_SCAN_MAX:
            break
        if needle and not _matches(row, needle):
            continue
        if start <= total < start + size:
            picked.append(row)
        total += 1
    return picked, total, needle and scanned > SEARCH_SCAN_MAX


def _csv_rows(path: Path):
    with path.open(newline="", encoding="utf-8-sig", errors="replace") as handle:
        for row in csv.reader(handle):
            yield [str(cell) for cell in row]


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    return str(value)


def read_table(path: Path, sheet: Optional[str], page: int, size: int, query: str) -> dict:
    page = max(1, page)
    size = max(1, min(size, PAGE_SIZE_MAX))
    needle = (query or "").strip().lower()
    sheets: List[str] = []
    chosen = None

    if path.suffix.lower() == ".csv":
        rows = _csv_rows(path)
        header = next(rows, [])
        picked, total, truncated = _page(rows, page, size, needle)
    else:
        import openpyxl

        try:
            source = path
            if not isinstance(path, Path):  # a stored file: workspace sheets are small
                import io

                source = io.BytesIO(path.read_bytes())
            book = openpyxl.load_workbook(source, read_only=True, data_only=True)
        except Exception as exc:
            raise ValidationError(f"This Excel file could not be opened: {exc}") from exc
        try:
            sheets = list(book.sheetnames)
            chosen = sheet if sheet in sheets else (sheets[0] if sheets else None)
            if chosen is None:
                header, picked, total, truncated = [], [], 0, False
            else:
                values = ([_cell(c) for c in row] for row in book[chosen].iter_rows(values_only=True))
                header = next(values, [])
                picked, total, truncated = _page(values, page, size, needle)
        finally:
            book.close()

    width = max([len(header)] + [len(r) for r in picked]) if (header or picked) else 0
    return {
        "columns": header + [""] * (width - len(header)),
        "rows": [r + [""] * (width - len(r)) for r in picked],
        "total": total,
        "page": page,
        "size": size,
        "sheets": sheets,
        "sheet": chosen,
        "truncated": bool(truncated),
    }


def read_text(path: Path) -> dict:
    with path.open("rb") as handle:
        data = handle.read(TEXT_LIMIT_BYTES + 1)
    return {
        "text": data[:TEXT_LIMIT_BYTES].decode("utf-8", errors="replace"),
        "truncated": len(data) > TEXT_LIMIT_BYTES,
    }
