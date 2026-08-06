"""Application document endpoints.

Documents belong to an application, not to a patient directly -- so
uploading and listing are scoped by application id, and a patient's
documents are reached through their applications.

Access is gated on the application permissions rather than a new model:
these files are part of a submission, so anyone who may read an
application may read its documents, and uploading/removing is an
application:update. That keeps existing roles working unchanged.

There is no per-file approve/reject here. A reviewer's verdict is
recorded once, on the application row (PUT /applications/{id}).
"""
import uuid
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse

from app.crud import file_metadata as metadata_crud
from app.crud import patient_application_files as crud
from app.crud import patient_applications as applications_crud
from app.db import get_cursor
from app.deid import dispatch_deidentification, queued_status
from app.errors import NotFoundError, ValidationError
from app.file_metadata import extract
from app.logging_setup import get_logger
from app.schemas import (
    FileMetadata,
    FileMetadataCreate,
    PatientApplicationFile,
    PatientApplicationFileUpdate,
    User,
)
from app.security import require_permission
from app.storage import (
    delete_file as remove_from_disk,
    file_extension,
    guess_mime_type,
    resolve_stored_path,
    sanitize_filename,
    write_file,
)

log = get_logger(__name__)

router = APIRouter(tags=["application-files"])

# A folder upload can contain anything; refuse implausible sizes rather
# than reading them into memory.
MAX_FILE_BYTES = 50 * 1024 * 1024


def _record_metadata(cursor, file_id: str, path, extension: str) -> None:
    """Extract and store metadata for one just-uploaded file.

    Deliberately swallowing: the bytes are on disk and the file row
    exists, so a metadata failure is a missing panel in the UI, not a
    lost document. extract() already records *why* it failed on the row;
    this catch is for the Hive write itself.
    """
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
    # 404 on an unknown application rather than an empty list, so a wrong
    # id is distinguishable from an application with no documents.
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
    """Accepts many files at once -- the client sends a whole folder.

    Each file is written to disk first, its row inserted after, and its
    metadata extracted last. That order is deliberate: a failed write
    never leaves a row pointing at nothing, and metadata is derived from
    a file that is already safely stored. The reverse (orphaned bytes
    with no row) is recoverable; a dangling row is not.
    """
    applications_crud.get_application_or_404(cursor, application_id)

    if not files:
        raise ValidationError("No files were uploaded")

    created: List[PatientApplicationFile] = []

    for upload in files:
        raw_name = upload.filename or "file"
        data = await upload.read()

        if len(data) == 0:
            # Selecting a folder can yield directory entries and hidden
            # files; skipping beats failing the whole batch.
            log.info("skipping_empty_upload", name=raw_name)
            continue

        if len(data) > MAX_FILE_BYTES:
            raise ValidationError(
                f"'{raw_name}' is larger than the {MAX_FILE_BYTES // (1024 * 1024)}MB limit"
            )

        sanitized = sanitize_filename(raw_name)
        extension = file_extension(raw_name)
        record_id = str(uuid.uuid4())
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
    """The metadata extracted at upload time.

    404 when there is no row at all, which means the file predates
    extraction. A file whose format we do not read still *has* a row --
    status 'unsupported' -- so the UI can tell "nothing to show" apart
    from "never looked".
    """
    crud.get_file_or_404(cursor, file_id)

    record = metadata_crud.get_metadata_for_file(cursor, file_id)
    if record is None:
        raise NotFoundError(f"No metadata recorded for file '{file_id}'")
    return record


@router.get("/files/{file_id}/content")
def download_application_file(
    file_id: str,
    deidentified: bool = False,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("application:view")),
):
    """Serves the bytes.

    `deidentified=true` returns the redacted copy instead, once the OCR
    job has produced one. Inline disposition so a PDF opens in the
    browser's viewer rather than downloading.
    """
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
    """Queues OCR + PII redaction for one file.

    Returns immediately with the row marked as queued; the work runs
    elsewhere and the row is updated when it finishes. The client re-reads
    to see the result -- no socket, by design.

    Where "elsewhere" is depends on DEID_BACKEND: this process's
    background task, or a Cloudera AI Job run. Both end up in the same
    run_deidentification(), so the contract here does not change either
    way -- including which status the row lands in, which the deid module
    owns because the two backends need different ones.
    """
    record = crud.get_file_or_404(cursor, file_id)

    # 'pending' is deliberately not in this list: that is the state every
    # file is uploaded in, so rejecting it would make a document
    # impossible to de-identify the first time.
    if record.deid_status in ("queued", "processing"):
        raise ValidationError("This file is already queued for de-identification")

    if record.file_extension.lower() != "pdf":
        raise ValidationError(
            f"Only PDF files can be de-identified (got '{record.file_extension}')"
        )

    # Marked before dispatch so the UI reflects it on the very next read,
    # rather than looking like nothing happened.
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


@router.delete("/files/{file_id}", status_code=204)
def delete_application_file(
    file_id: str,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("application:update")),
):
    record = crud.delete_file(cursor, file_id)
    # Metadata next, then the bytes. Row first throughout: an orphaned
    # file on disk is harmless, a row pointing at nothing is not.
    metadata_crud.delete_metadata_for_files(cursor, [file_id])
    remove_from_disk(record.file_path)
    if record.de_identified_file_path:
        remove_from_disk(record.de_identified_file_path)
