"""Patient document endpoints.

Access is gated on the patients permissions rather than a new model:
these files belong to a patient, so anyone who may read a patient may
read their documents, and uploading/removing is a patient:update.
That keeps existing roles working unchanged.
"""
import uuid
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse

from app.audit import record_audit
from app.crud import patient_files as crud
from app.crud import patients as patients_crud
from app.db import get_cursor
from app.deid import run_deidentification
from app.errors import ValidationError
from app.logging_setup import get_logger
from app.schemas import PatientFile, PatientFileReview, PatientFileUpdate, User
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

router = APIRouter(tags=["patient-files"])

# A folder upload can contain anything; refuse implausible sizes rather
# than reading them into memory.
MAX_FILE_BYTES = 50 * 1024 * 1024


@router.get("/patients/{patient_id}/files", response_model=List[PatientFile])
def list_patient_files(
    patient_id: str,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("patient:view")),
):
    # 404 on an unknown patient rather than an empty list, so a wrong id
    # is distinguishable from a patient with no documents.
    patients_crud.get_patient_or_404(cursor, patient_id)
    return crud.list_files(cursor, patient_id)


@router.post(
    "/patients/{patient_id}/files", response_model=List[PatientFile], status_code=201
)
async def upload_patient_files(
    patient_id: str,
    files: List[UploadFile] = File(...),
    description: Optional[str] = Form(default=None),
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("patient:update")),
):
    """Accepts many files at once -- the client sends a whole folder.

    Each file is written to disk first and its row inserted after, so a
    failed write never leaves a row pointing at nothing. The reverse
    (orphaned bytes with no row) is recoverable; a dangling row is not.
    """
    patients_crud.get_patient_or_404(cursor, patient_id)

    if not files:
        raise ValidationError("No files were uploaded")

    created: List[PatientFile] = []

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
        stored_path = write_file(patient_id, record_id, sanitized, data)

        created.append(
            crud.create_file(
                cursor,
                patient_id=patient_id,
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

    log.info("patient_files_uploaded", patient_id=patient_id, count=len(created))
    return created


@router.get("/files/{file_id}", response_model=PatientFile)
def get_patient_file(
    file_id: str,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("patient:view")),
):
    return crud.get_file_or_404(cursor, file_id)


@router.get("/files/{file_id}/content")
def download_patient_file(
    file_id: str,
    deidentified: bool = False,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("patient:view")),
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
        filename = record.de_identified_file_name or record.sanitized_file_name
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


@router.post("/files/{file_id}/deidentify", response_model=PatientFile)
def deidentify_patient_file(
    file_id: str,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("patient:update")),
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
        cursor, file_id, PatientFileUpdate(deid_status="processing")
    )

    background.add_task(
        run_deidentification,
        file_id=file_id,
        request_id=request.headers.get("X-Request-ID"),
    )

    log.info("deid_queued", file_id=file_id, patient_id=record.patient_id)
    return updated


@router.post("/files/{file_id}/review", response_model=PatientFile)
def review_patient_file(
    file_id: str,
    payload: PatientFileReview,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("application:update")),
):
    """Approve or reject one document.

    Gated on application:update rather than patient:update -- reviewing a
    submission is the application reviewer's job, which is not the same
    grant as being allowed to edit patient records.
    """
    before = crud.get_file_or_404(cursor, file_id)
    reviewed = crud.review_file(cursor, file_id, payload, reviewer_id=actor.id)

    background.add_task(
        record_audit,
        action="UPDATE",
        entity_type="patient_file",
        entity_id=file_id,
        old_values=before.model_dump(mode="json"),
        new_values=reviewed.model_dump(mode="json"),
        request_id=request.headers.get("X-Request-ID"),
    )
    return reviewed


@router.put("/files/{file_id}", response_model=PatientFile)
def update_patient_file(
    file_id: str,
    payload: PatientFileUpdate,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("patient:update")),
):
    return crud.update_file(cursor, file_id, payload)


@router.delete("/files/{file_id}", status_code=204)
def delete_patient_file(
    file_id: str,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("patient:update")),
):
    record = crud.delete_file(cursor, file_id)
    # Row first, bytes after: an orphaned file on disk is harmless, a row
    # pointing at nothing is not.
    remove_from_disk(record.file_path)
    if record.de_identified_file_path:
        remove_from_disk(record.de_identified_file_path)
