"""Customer document endpoints.

Access is gated on the customers permissions rather than a new model:
these files belong to a customer, so anyone who may read a customer may
read their documents, and uploading/removing is a customers:update.
That keeps existing roles working unchanged.
"""
import uuid
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse

from app.crud import customer_files as crud
from app.crud import customers as customers_crud
from app.db import get_cursor
from app.deid import run_deidentification
from app.errors import ValidationError
from app.logging_setup import get_logger
from app.schemas import CustomerFile, CustomerFileUpdate, User
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

router = APIRouter(tags=["customer-files"])

# A folder upload can contain anything; refuse implausible sizes rather
# than reading them into memory.
MAX_FILE_BYTES = 50 * 1024 * 1024


@router.get("/customers/{customer_id}/files", response_model=List[CustomerFile])
def list_customer_files(
    customer_id: str,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("customers:read")),
):
    # 404 on an unknown customer rather than an empty list, so a wrong id
    # is distinguishable from a customer with no documents.
    customers_crud.get_customer_or_404(cursor, customer_id)
    return crud.list_files(cursor, customer_id)


@router.post(
    "/customers/{customer_id}/files", response_model=List[CustomerFile], status_code=201
)
async def upload_customer_files(
    customer_id: str,
    files: List[UploadFile] = File(...),
    description: Optional[str] = Form(default=None),
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("customers:update")),
):
    """Accepts many files at once -- the client sends a whole folder.

    Each file is written to disk first and its row inserted after, so a
    failed write never leaves a row pointing at nothing. The reverse
    (orphaned bytes with no row) is recoverable; a dangling row is not.
    """
    customers_crud.get_customer_or_404(cursor, customer_id)

    if not files:
        raise ValidationError("No files were uploaded")

    created: List[CustomerFile] = []

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
        record_id = str(uuid.uuid4())
        stored_path = write_file(customer_id, record_id, sanitized, data)

        created.append(
            crud.create_file(
                cursor,
                customer_id=customer_id,
                original_file_name=raw_name,
                sanitized_file_name=sanitized,
                file_extension=file_extension(raw_name),
                mime_type=guess_mime_type(raw_name, upload.content_type),
                file_size=len(data),
                file_path=str(stored_path),
                description=description,
                file_id=record_id,
            )
        )

    if not created:
        raise ValidationError("None of the selected files contained any data")

    log.info("customer_files_uploaded", customer_id=customer_id, count=len(created))
    return created


@router.get("/files/{file_id}", response_model=CustomerFile)
def get_customer_file(
    file_id: str,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("customers:read")),
):
    return crud.get_file_or_404(cursor, file_id)


@router.get("/files/{file_id}/content")
def download_customer_file(
    file_id: str,
    deidentified: bool = False,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("customers:read")),
):
    """Serves the bytes.

    `deidentified=true` returns the redacted copy instead, once the OCR
    job has produced one. Inline disposition so a PDF opens in the
    browser's viewer rather than downloading.
    """
    record = crud.get_file_or_404(cursor, file_id)

    if deidentified:
        if not record.deidentified_file_path:
            raise ValidationError("This file has not been de-identified yet")
        path = resolve_stored_path(record.deidentified_file_path)
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


@router.post("/files/{file_id}/deidentify", response_model=CustomerFile)
def deidentify_customer_file(
    file_id: str,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("customers:update")),
):
    """Queues OCR + PII redaction for one file.

    Returns immediately with the row marked 'processing'; the work runs in
    the background and the row is updated when it finishes. The client
    re-reads to see the result -- no socket, by design.

    The same run_deidentification() is what a Cloudera AI job will call
    when this moves off the API process, so the contract does not change.
    """
    record = crud.get_file_or_404(cursor, file_id)

    if record.deid_status == "processing":
        raise ValidationError("This file is already being de-identified")

    if record.file_extension.lower() != "pdf":
        raise ValidationError(
            f"Only PDF files can be de-identified (got '{record.file_extension}')"
        )

    # Marked before the task starts so the UI reflects it on the very next
    # read, rather than looking like nothing happened.
    updated = crud.update_file(
        cursor, file_id, CustomerFileUpdate(deid_status="processing")
    )

    background.add_task(
        run_deidentification,
        file_id=file_id,
        request_id=request.headers.get("X-Request-ID"),
    )

    log.info("deid_queued", file_id=file_id, customer_id=record.customer_id)
    return updated


@router.put("/files/{file_id}", response_model=CustomerFile)
def update_customer_file(
    file_id: str,
    payload: CustomerFileUpdate,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("customers:update")),
):
    return crud.update_file(cursor, file_id, payload)


@router.delete("/files/{file_id}", status_code=204)
def delete_customer_file(
    file_id: str,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("customers:update")),
):
    record = crud.delete_file(cursor, file_id)
    # Row first, bytes after: an orphaned file on disk is harmless, a row
    # pointing at nothing is not.
    remove_from_disk(record.file_path)
    if record.deidentified_file_path:
        remove_from_disk(record.deidentified_file_path)
