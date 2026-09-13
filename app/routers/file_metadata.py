from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Response

from app.crud import file_metadata as crud
from app.crud import patient_application_files as files_crud
from app.crud import patient_applications as applications_crud
from app.access_log import EXPORT, READ, record_access
from app.db import get_cursor
from app.logging_setup import get_logger
from app.schemas import FileMetadataRow, User
from app.security import require_permission
from app.xlsx import workbook_bytes

log = get_logger(__name__)

router = APIRouter(prefix="/file-metadata", tags=["file-metadata"])

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
    actor: User = Depends(require_permission("application:view")),
):
    rows = _filtered(
        _rows(cursor), search=search, status=status, file_type=file_type,
        patient_id=patient_id,
    )
    log.info("file_metadata_listed", count=len(rows), search=search or "")
    record_access(
        READ,
        actor=actor,
        resource_type="file_metadata",
        record_count=len(rows),
        detail=f"search={search or ''}",
    )
    return rows


def _metadata_keys(rows: List[FileMetadataRow]) -> List[str]:
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
    actor: User = Depends(require_permission("application:view")),
):
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
    record_access(
        EXPORT,
        actor=actor,
        resource_type="file_metadata",
        record_count=len(rows),
        identified=True,
        detail=f"search={search or ''} status={status or ''} type={file_type or ''}",
    )

    return Response(
        content=content,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
