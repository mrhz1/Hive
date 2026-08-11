"""Browsing and exporting everything in `file_metadata`.

The per-file endpoints in patient_application_files.py answer "what is in
this document?". This router answers the other question -- "which
documents have this in them?" -- which needs the whole table, the file
each row describes, and a search that reaches inside the extracted blob.

A stored row knows only a file id, so the file and its application are
joined on in Python. Hive is asked for three flat SELECTs rather than one
three-way join: the tables are small, and the join keeps working when a
file has been deleted out from under its metadata.
"""
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Response

from app.crud import file_metadata as crud
from app.crud import patient_application_files as files_crud
from app.crud import patient_applications as applications_crud
from app.db import get_cursor
from app.logging_setup import get_logger
from app.schemas import FileMetadataRow, User
from app.security import require_permission
from app.xlsx import workbook_bytes

log = get_logger(__name__)

router = APIRouter(prefix="/file-metadata", tags=["file-metadata"])

# Columns that come before the extracted fields in an export.
EXPORT_HEADERS = (
    "File",
    "File id",
    "Patient id",
    "Application id",
    "Type",
    "Status",
    "Error",
    "Extracted at",
)


def _rows(cursor) -> List[FileMetadataRow]:
    """Every metadata row, with its file and patient attached."""
    files = {record.id: record for record in files_crud.list_files(cursor)}
    patients = {
        application.id: application.patient_id
        for application in applications_crud.list_applications(cursor)
    }

    out: List[FileMetadataRow] = []
    for record in crud.list_metadata(cursor):
        document = files.get(record.file_id)
        application_id = document.application_id if document else None
        out.append(
            FileMetadataRow(
                **record.model_dump(),
                file_name=document.original_file_name if document else None,
                application_id=application_id,
                patient_id=patients.get(application_id or "") or None,
            )
        )
    return out


def _haystack(row: FileMetadataRow) -> str:
    """Everything about a row that a search term could plausibly mean.

    The extracted keys are in here as well as the values: somebody
    hunting for every scan that carries a 'PatientBirthDate' at all is
    asking a real question.
    """
    parts = [
        row.file_name or "",
        row.file_id,
        row.application_id or "",
        row.patient_id or "",
        row.file_type,
        row.status,
        row.error or "",
    ]
    for key, value in row.metadata.items():
        parts.append(str(key))
        parts.append("" if value is None else str(value))
    return " ".join(parts).lower()


def _filtered(
    rows: List[FileMetadataRow],
    search: Optional[str],
    status: Optional[str],
    file_type: Optional[str],
    patient_id: Optional[str],
) -> List[FileMetadataRow]:
    if status:
        rows = [r for r in rows if r.status == status]
    if file_type:
        wanted = file_type.lower()
        rows = [r for r in rows if (r.file_type or "").lower() == wanted]
    if patient_id:
        rows = [r for r in rows if r.patient_id == patient_id]

    term = (search or "").strip().lower()
    if term:
        rows = [r for r in rows if term in _haystack(r)]

    return rows


@router.get("", response_model=List[FileMetadataRow])
def list_file_metadata(
    search: Optional[str] = None,
    status: Optional[str] = None,
    file_type: Optional[str] = None,
    patient_id: Optional[str] = None,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("application:view")),
):
    """Extracted metadata across every document, newest first."""
    rows = _filtered(
        _rows(cursor), search=search, status=status, file_type=file_type,
        patient_id=patient_id,
    )
    log.info("file_metadata_listed", count=len(rows), search=search or "")
    return rows


def _metadata_keys(rows: List[FileMetadataRow]) -> List[str]:
    """Every extracted field present anywhere in the exported set."""
    keys = {key for row in rows for key in row.metadata}
    return sorted(keys)


def _export_row(row: FileMetadataRow, keys: List[str]) -> list:
    extracted: Dict[str, object] = row.metadata
    return [
        row.file_name or "",
        row.file_id,
        row.patient_id or "",
        row.application_id or "",
        row.file_type,
        row.status,
        row.error or "",
        row.created_at.isoformat(timespec="seconds"),
        *[extracted.get(key, "") for key in keys],
    ]


@router.get("/export")
def export_file_metadata(
    search: Optional[str] = None,
    status: Optional[str] = None,
    file_type: Optional[str] = None,
    patient_id: Optional[str] = None,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("application:view")),
):
    """The filtered table as an Excel workbook.

    Takes the same filters as the listing, so what downloads is what the
    table was showing -- one row per document, one column per extracted
    field that any of them carries.
    """
    rows = _filtered(
        _rows(cursor), search=search, status=status, file_type=file_type,
        patient_id=patient_id,
    )

    keys = _metadata_keys(rows)

    content = workbook_bytes(
        headers=(*EXPORT_HEADERS, *keys),
        rows=[_export_row(row, keys) for row in rows],
        sheet_title="File metadata",
    )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    name = f"file-metadata-{stamp}.xlsx"

    log.info("file_metadata_exported", count=len(rows), fields=len(keys))

    return Response(
        content=content,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
