"""Application document endpoints."""
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Request, UploadFile
from fastapi import Response
from fastapi.responses import FileResponse

from app.crud import file_metadata as metadata_crud
from app.crud import patient_application_files as crud
from app.crud import patient_applications as applications_crud
from app.crud import patients as patients_crud
from app.db import get_cursor
from app.deid import (
    DEIDENTIFIABLE_LABEL,
    dispatch_deidentification,
    is_deidentifiable,
    queued_status,
)
from app.errors import NotFoundError, ValidationError
from app.file_metadata import extract
from app.logging_setup import get_logger
from app.schemas import (
    FileMetadata,
    FileReview,
    FileMetadataCreate,
    PatientApplicationFile,
    PatientApplicationFileUpdate,
    User,
)
from app.security import require_permission
from app.xlsx import workbook_bytes
from app.storage import (
    delete_file as remove_from_disk,
    file_extension,
    guess_mime_type,
    resolve_stored_path,
    sanitize_filename,
    write_file,
    write_patient_document,
)

log = get_logger(__name__)

router = APIRouter(tags=["application-files"])

MAX_FILE_BYTES = 50 * 1024 * 1024


def _known_patient_id(cursor, application) -> Optional[str]:
    """The patient this application belongs to, if they are on file."""
    patient_id = getattr(application, "patient_id", None)
    if not patient_id:
        return None

    return patient_id if patients_crud.get_patient(cursor, patient_id) else None


def _record_metadata(cursor, file_id: str, path, extension: str) -> None:
    """Extract and store metadata for one just-uploaded file."""
    file_type, metadata, status, error = extract(path, extension)
    try:
        metadata_crud.create_metadata(
            cursor,
            FileMetadataCreate(
                file_id=file_id,
                file_type=file_type,
                metadata=metadata,
                status=status,
                error=error,
            ),
        )
    except Exception as exc:  # pragma: no cover - defensive
        log.error("file_metadata_write_failed", file_id=file_id, error=str(exc))


@router.get(
    "/applications/{application_id}/files",
    response_model=List[PatientApplicationFile],
)
def list_application_files(
    application_id: str,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("application:view")),
):
    applications_crud.get_application_or_404(cursor, application_id)
    return crud.list_files(cursor, application_id)


@router.post(
    "/applications/{application_id}/files",
    response_model=List[PatientApplicationFile],
    status_code=201,
)
async def upload_application_files(
    application_id: str,
    files: List[UploadFile] = File(...),
    description: Optional[str] = Form(default=None),
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("application:update")),
):
    """Accepts many files at once -- the client sends a whole folder."""
    application = applications_crud.get_application_or_404(cursor, application_id)

    if not files:
        raise ValidationError("No files were uploaded")

    received_at = datetime.now(timezone.utc)
    patient_id = _known_patient_id(cursor, application)

    created: List[PatientApplicationFile] = []

    for upload in files:
        raw_name = upload.filename or "file"
        data = await upload.read()

        if len(data) == 0:
            log.info("skipping_empty_upload", name=raw_name)
            continue

        if len(data) > MAX_FILE_BYTES:
            raise ValidationError(
                f"'{raw_name}' is larger than the {MAX_FILE_BYTES // (1024 * 1024)}MB limit"
            )

        extension = file_extension(raw_name)
        record_id = str(uuid.uuid4())

        if patient_id:
            stored_path = write_patient_document(
                patient_id, extension, data, received_at
            )
            sanitized = stored_path.name
        else:
            sanitized = sanitize_filename(raw_name)
            stored_path = write_file(application_id, record_id, sanitized, data)

        record = crud.create_file(
            cursor,
            application_id=application_id,
            original_file_name=raw_name,
            sanitized_file_name=sanitized,
            file_extension=extension,
            mime_type=guess_mime_type(raw_name, upload.content_type),
            file_size=len(data),
            file_path=str(stored_path),
            description=description,
            file_id=record_id,
        )
        _record_metadata(cursor, record.id, stored_path, extension)
        created.append(record)

    if not created:
        raise ValidationError("None of the selected files contained any data")

    log.info(
        "application_files_uploaded",
        application_id=application_id,
        count=len(created),
    )
    return created


@router.get("/files/{file_id}", response_model=PatientApplicationFile)
def get_application_file(
    file_id: str,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("application:view")),
):
    return crud.get_file_or_404(cursor, file_id)


@router.get("/files/{file_id}/metadata", response_model=FileMetadata)
def get_application_file_metadata(
    file_id: str,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("application:view")),
):
    """The metadata extracted at upload time."""
    crud.get_file_or_404(cursor, file_id)

    record = metadata_crud.get_metadata_for_file(cursor, file_id)
    if record is None:
        raise NotFoundError(f"No metadata recorded for file '{file_id}'")
    return record


@router.get("/files/{file_id}/metadata/export")
def export_application_file_metadata(
    file_id: str,
    fields: Optional[str] = None,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("application:view")),
):
    """The metadata as an Excel workbook."""
    crud.get_file_or_404(cursor, file_id)

    record = metadata_crud.get_metadata_for_file(cursor, file_id)
    if record is None:
        raise NotFoundError(f"No metadata recorded for file '{file_id}'")

    wanted = [name.strip() for name in (fields or "").split(",") if name.strip()]
    items = sorted(record.metadata.items())
    if wanted:
        keep = set(wanted)
        items = [(name, value) for name, value in items if name in keep]

    content = workbook_bytes(
        headers=("Field", "Value"),
        rows=items,
        sheet_title="Metadata",
    )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    name = f"metadata-{file_id[:8]}-{stamp}.xlsx"

    return Response(
        content=content,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/files/{file_id}/content")
def download_application_file(
    file_id: str,
    deidentified: bool = False,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("application:view")),
):
    """Serves the bytes."""
    record = crud.get_file_or_404(cursor, file_id)

    if deidentified:
        if not record.de_identified_file_path:
            raise ValidationError("This file has not been de-identified yet")
        path = resolve_stored_path(record.de_identified_file_path)
        filename = record.deidentified_file_name or record.sanitized_file_name
    else:
        path = resolve_stored_path(record.file_path)
        filename = record.sanitized_file_name

    if not path.is_file():
        raise ValidationError("The stored file is missing from disk")

    return FileResponse(
        path,
        media_type=record.mime_type,
        filename=filename,
        content_disposition_type="inline",
    )


@router.post("/files/{file_id}/deidentify", response_model=PatientApplicationFile)
def deidentify_application_file(
    file_id: str,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("application:update")),
):
    """Queues OCR + PII redaction for one file."""
    record = crud.get_file_or_404(cursor, file_id)

    if record.deid_status in ("queued", "processing"):
        raise ValidationError("This file is already queued for de-identification")

    if not is_deidentifiable(record.file_extension):
        raise ValidationError(
            f"'{record.file_extension}' files cannot be de-identified "
            f"(handled: {DEIDENTIFIABLE_LABEL})"
        )

    updated = crud.update_file(
        cursor, file_id, PatientApplicationFileUpdate(deid_status=queued_status())
    )

    background.add_task(
        dispatch_deidentification,
        file_id=file_id,
        request_id=request.headers.get("X-Request-ID"),
    )

    log.info("deid_queued", file_id=file_id, application_id=record.application_id)
    return updated


@router.put("/files/{file_id}", response_model=PatientApplicationFile)
def update_application_file(
    file_id: str,
    payload: PatientApplicationFileUpdate,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("application:update")),
):
    return crud.update_file(cursor, file_id, payload)


@router.post("/files/{file_id}/review", response_model=PatientApplicationFile)
def review_application_file(
    file_id: str,
    payload: FileReview,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("application:update")),
):
    """Record a reviewer's verdict on one document."""
    crud.get_file_or_404(cursor, file_id)

    note = (payload.review_note or "").strip()
    if payload.review_status == "rejected" and not note:
        raise ValidationError("A reason is required when rejecting a file")

    return crud.update_file(
        cursor,
        file_id,
        PatientApplicationFileUpdate(
            review_status=payload.review_status,
            review_note=note or None,
        ),
    )


@router.delete("/files/{file_id}", status_code=204)
def delete_application_file(
    file_id: str,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("application:update")),
):
    record = crud.delete_file(cursor, file_id)
    metadata_crud.delete_metadata_for_files(cursor, [file_id])
    remove_from_disk(record.file_path)
    if record.de_identified_file_path:
        remove_from_disk(record.de_identified_file_path)
