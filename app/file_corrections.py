"""Changing a redacted file's modality and date, one at a time (the review
screen) or in bulk from a spreadsheet (scripts/update_file_metadata.py, 7.9).

The spreadsheet's first row names the columns:

    File            the redacted file name (AA1234_MR_..._R.dcm) or file id
    Modality        new modality (a DICOM code or MRI, Echo, ...); blank keeps it
    Document date   new date, YYYY-MM-DD or an Excel date; blank keeps it
    Reject reason   if set, the file is rejected with this reason: it goes to
                    Rejections, e.g. an identifier is still visible in the
                    picture, and stays out of Zone 2 until replaced

The script renames files of any application except deleted ones, including
submitted ones; the review screen can't rename submitted files.
"""

from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from app import document_info
from app.crud import patient_application_files as crud
from app.errors import ValidationError
from app.logging_setup import get_logger
from app.patient_import import _key, _read_rows, _text
from app.purge import is_deleted_file
from app.schemas import PatientApplicationFile, PatientApplicationFileUpdate
from app.storage import resolve_stored_path

log = get_logger(__name__)

COLUMNS = {
    "file": "file",
    "filename": "file",
    "fileid": "file",
    "modality": "modality",
    "documentdate": "date",
    "date": "date",
    "rejectreason": "reject",
    "reject": "reject",
}


def rename_document(
    cursor, record: PatientApplicationFile, info: document_info.DocumentInfo
) -> Tuple[PatientApplicationFile, str, str]:
    """Rename the de-identified copy (and its sidecar) to `info`; returns
    the updated record and the old and new names."""
    if not record.de_identified_file_path:
        raise ValidationError(
            f"'{record.original_file_name}' has no de-identified copy to rename"
        )
    current = resolve_stored_path(record.de_identified_file_path)
    if not current.is_file():
        raise ValidationError("The de-identified copy is missing from disk")
    if document_info.renamed(current.name, info) is None:
        raise ValidationError(f"'{current.name}' is not named like a redacted file")
    try:
        target = document_info.rename(current, info)
    except FileExistsError as e:
        raise ValidationError(str(e))

    if target == current:
        return record, current.name, current.name

    changes = PatientApplicationFileUpdate(
        deidentified_file_name=target.name,
        de_identified_file_path=str(target),
    )
    if record.sanitized_file_name == current.name:
        changes.sanitized_file_name = target.name
    return crud.update_file(cursor, record.id, changes), current.name, target.name


# --- bulk corrections -----------------------------------------------------------


class CorrectionRow(BaseModel):
    line: int
    file: str = ""
    action: str  # rename, reject, unchanged, error
    old_name: Optional[str] = None
    new_name: Optional[str] = None
    errors: List[str] = Field(default_factory=list)


def _date_value(raw) -> Optional[str]:
    if isinstance(raw, datetime):
        raw = raw.date()
    if isinstance(raw, date):
        return raw.strftime("%Y%m%d")
    text = _text(raw)
    return None if text is None else text


def correct(cursor, name: str, data: bytes, apply: bool) -> List[CorrectionRow]:
    rows = _read_rows(name, data)
    while rows and not any(_text(v) for v in rows[0]):
        rows.pop(0)
    if not rows:
        raise ValidationError("The file is empty")
    columns = [COLUMNS.get(_key(h)) for h in rows[0]]
    if "file" not in columns:
        raise ValidationError("No 'File' column in the first row")

    records = crud.list_files(cursor)
    by_name: Dict[str, PatientApplicationFile] = {}
    for record in records:
        by_name[record.id] = record
        if record.deidentified_file_name:
            by_name[record.deidentified_file_name] = record

    out: List[CorrectionRow] = []
    for line, raw in enumerate(rows[1:], start=2):
        if not any(_text(v) for v in raw):
            continue
        values = {c: v for c, v in zip(columns, raw) if c}
        wanted = _text(values.get("file")) or ""
        row = CorrectionRow(line=line, file=wanted, action="unchanged")
        out.append(row)

        record = by_name.get(wanted)
        if record is None:
            row.action, row.errors = "error", [f"No file '{wanted}'"]
            continue
        if is_deleted_file(record):
            row.action, row.errors = "error", ["The file was deleted"]
            continue
        parts = document_info.parse_name(record.deidentified_file_name or "") or {}
        row.old_name = row.new_name = record.deidentified_file_name

        modality = parts.get("modality") or document_info.UNKNOWN
        typed = _text(values.get("modality"))
        if typed:
            modality = document_info.clean_modality(typed)
            if modality is None:
                row.errors.append(f"'{typed}' is not a known modality")

        day = parts.get("day") if parts.get("modality") else document_info.UNKNOWN
        typed_day = _date_value(values.get("date"))
        if typed_day:
            day = document_info.clean_date(typed_day)
            if day is None:
                row.errors.append(f"'{typed_day}' is not a date (use YYYY-MM-DD)")

        reason = _text(values.get("reject"))
        if row.errors:
            row.action = "error"
            continue

        info = document_info.DocumentInfo(modality=modality, date=day)
        new_name = document_info.renamed(record.deidentified_file_name or "", info)
        if new_name is None:
            row.action, row.errors = "error", ["Not named like a redacted file"]
            continue
        if new_name != record.deidentified_file_name:
            row.action, row.new_name = "rename", new_name
        if reason and record.review_status != "rejected":
            row.action = "reject" if row.action == "unchanged" else "rename+reject"

        if not apply or row.action == "unchanged":
            continue
        try:
            if new_name != record.deidentified_file_name:
                record, _old, row.new_name = rename_document(cursor, record, info)
            if reason and record.review_status != "rejected":
                crud.update_file(
                    cursor,
                    record.id,
                    PatientApplicationFileUpdate(review_status="rejected", review_note=reason),
                )
        except ValidationError as e:
            row.action, row.errors = "error", [str(e)]
    log.info(
        "file_corrections",
        applied=apply,
        rows=len(out),
        changed=sum(1 for r in out if r.action not in ("unchanged", "error")),
        errors=sum(1 for r in out if r.action == "error"),
    )
    return out
