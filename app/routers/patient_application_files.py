"""Application document endpoints."""
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Request, UploadFile
from fastapi import Response
from fastapi.responses import FileResponse

from app import uploads
from app.crud import file_metadata as metadata_crud
from app.crud import patient_application_files as crud
from app.crud import patient_applications as applications_crud
from app.db import get_cursor
from app.deid import (
    DEIDENTIFIABLE_LABEL,
    dispatch_deidentification,
    is_deidentifiable,
    queued_status,
)
from app.errors import NotFoundError, ValidationError
from app.access_log import DOWNLOAD, EXPORT, READ, record_access
from app.filetype import SNIFF_BYTES, resolve_extension
from app.logging_setup import get_logger
from app.preview import read_word_document, render_dicom_png
from app.schemas import (
    BulkResult,
    FileMetadata,
    FileReview,
    PatientApplicationFile,
    PatientApplicationFileUpdate,
    UploadJob,
    User,
    WordPreview,
)
from app.security import require_permission
from app.uploads import known_patient_id as _known_patient_id
from app.uploads import record_metadata as _record_metadata
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


def _too_large(name: str) -> ValidationError:
    return ValidationError(
        f"'{name}' is larger than the {MAX_FILE_BYTES // (1024 * 1024)}MB limit"
    )


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
            raise _too_large(raw_name)

        # A DICOM off a PACS often arrives with no extension at all.
        extension = resolve_extension(raw_name, data[:SNIFF_BYTES])
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


@router.post(
    "/applications/{application_id}/files/background",
    response_model=UploadJob,
    status_code=202,
)
async def upload_application_files_in_background(
    application_id: str,
    background: BackgroundTasks,
    request: Request,
    files: List[UploadFile] = File(...),
    description: Optional[str] = Form(default=None),
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("application:update")),
):
    """Take the files now, move and record them afterwards.

    Same batch as the endpoint above, but the response comes back as soon
    as the bytes are safely staged rather than after every file has been
    written, inserted and parsed. Poll GET /upload-jobs/{id} for progress;
    the user the application is assigned to is emailed when it is over.
    """
    applications_crud.get_application_or_404(cursor, application_id)

    if not files:
        raise ValidationError("No files were uploaded")

    received_at = datetime.now(timezone.utc)
    job = uploads.create_job(application_id)

    staged = 0
    try:
        for index, upload in enumerate(files):
            raw_name = upload.filename or "file"
            data = await upload.read()

            if len(data) == 0:
                log.info("skipping_empty_upload", name=raw_name)
                continue

            if len(data) > MAX_FILE_BYTES:
                raise _too_large(raw_name)

            uploads.stage(job.id, index, raw_name, data, upload.content_type)
            uploads.register_file(job.id, raw_name)
            staged += 1
    except Exception as exc:
        # Nothing has been recorded yet, so there is nothing to unwind
        # beyond the bytes sitting in staging.
        uploads.abandon_job(job.id, str(exc))
        raise

    if not staged:
        reason = "None of the selected files contained any data"
        uploads.abandon_job(job.id, reason)
        raise ValidationError(reason)

    background.add_task(
        uploads.run_upload_job,
        job_id=job.id,
        application_id=application_id,
        description=description,
        actor_id=actor.id,
        received_at=received_at,
        request_id=request.headers.get("X-Request-ID"),
    )

    log.info(
        "application_files_staged",
        application_id=application_id,
        job_id=job.id,
        count=staged,
    )
    return uploads.get_job(job.id)


@router.get("/upload-jobs/{job_id}", response_model=UploadJob)
def get_upload_job(
    job_id: str,
    _actor: User = Depends(require_permission("application:view")),
):
    """Progress of one background batch."""
    job = uploads.get_job(job_id)
    if job is None:
        raise NotFoundError(
            f"Upload job '{job_id}' is not known -- it may have finished long "
            "ago, or the API may have restarted since it ran"
        )
    return job


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
    actor: User = Depends(require_permission("application:view")),
):
    """The metadata extracted at upload time."""
    document = crud.get_file_or_404(cursor, file_id)

    record = metadata_crud.get_metadata_for_file(cursor, file_id)
    if record is None:
        raise NotFoundError(f"No metadata recorded for file '{file_id}'")

    # The original's own metadata: names, MRNs, whatever the format held.
    _record_file_access(
        cursor, document, actor, READ, deidentified=False, detail="metadata"
    )
    return record


@router.get("/files/{file_id}/metadata/export")
def export_application_file_metadata(
    file_id: str,
    fields: Optional[str] = None,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("application:view")),
):
    """The metadata as an Excel workbook."""
    document = crud.get_file_or_404(cursor, file_id)

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

    _record_file_access(
        cursor,
        document,
        actor,
        EXPORT,
        deidentified=False,
        record_count=len(items),
        detail=name,
    )

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
    actor: User = Depends(require_permission("application:view")),
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

    _record_file_access(
        cursor,
        record,
        actor,
        DOWNLOAD,
        deidentified=deidentified,
        byte_count=record.file_size,
        detail=filename,
    )

    return FileResponse(
        path,
        media_type=record.mime_type,
        filename=filename,
        content_disposition_type="inline",
    )


def _patient_of(cursor, application_id: str) -> Optional[str]:
    """Whose application this is, for the access record.

    One extra SELECT per read. Denormalising `patient_id` onto the file
    row would remove it, at the cost of a column that can drift.
    """
    application = applications_crud.get_application(cursor, application_id)
    return getattr(application, "patient_id", None)


def _record_file_access(
    cursor, record, actor, action: str, *, deidentified: bool, **extra
) -> None:
    """One access event for a file, with what only this layer knows."""
    record_access(
        action,
        actor=actor,
        resource_type="application_file",
        resource_id=record.id,
        patient_id=_patient_of(cursor, record.application_id),
        application_id=record.application_id,
        # The same endpoints serve the original and the redacted copy;
        # only one of those is a disclosure.
        identified=not deidentified,
        **extra,
    )


def _preview_path(record, deidentified: bool):
    """The file to preview, and the extension that says how to read it."""
    if deidentified:
        if not record.de_identified_file_path:
            raise ValidationError("This file has not been de-identified yet")
        path = resolve_stored_path(record.de_identified_file_path)
        # The redacted copy of a Word document is always .docx, whatever
        # the original was; DICOM and PDF keep their input format.
        extension = "docx" if record.file_extension in ("doc", "docx") else record.file_extension
    else:
        path = resolve_stored_path(record.file_path)
        extension = record.file_extension

    if not path.is_file():
        raise ValidationError("The stored file is missing from disk")

    return path, (extension or "").lower()


def _dicom_response(path, frame: int) -> Response:
    content, frames = render_dicom_png(path, frame)
    return Response(
        content=content,
        media_type="image/png",
        headers={
            "X-Frame-Count": str(frames),
            # So the viewer can page through a multi-frame study without
            # re-reading the header separately.
            "Access-Control-Expose-Headers": "X-Frame-Count",
        },
    )


@router.get("/files/{file_id}/image")
def preview_application_file_image(
    file_id: str,
    frame: int = 0,
    deidentified: bool = False,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("application:view")),
):
    """One DICOM frame as a PNG, so a browser can show it."""
    record = crud.get_file_or_404(cursor, file_id)
    path, extension = _preview_path(record, deidentified)

    if extension not in ("dcm", "dicom"):
        raise ValidationError(f"'{extension}' files are not rendered as images")

    _record_file_access(
        cursor, record, actor, READ, deidentified=deidentified, detail=f"frame {frame}"
    )
    return _dicom_response(path, frame)


@router.get("/files/{file_id}/text", response_model=WordPreview)
def preview_application_file_text(
    file_id: str,
    deidentified: bool = False,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("application:view")),
):
    """A Word document's text, for a browser that would otherwise download it."""
    record = crud.get_file_or_404(cursor, file_id)
    path, extension = _preview_path(record, deidentified)

    if extension not in ("doc", "docx"):
        raise ValidationError(f"'{extension}' files are not rendered as text")

    _record_file_access(cursor, record, actor, READ, deidentified=deidentified)
    return read_word_document(path)


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


@router.post(
    "/applications/{application_id}/files/deidentify-all",
    response_model=BulkResult,
)
def deidentify_all_application_files(
    application_id: str,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("application:update")),
):
    """Queue every file on this application that can be de-identified.

    One request rather than one per file: an application can hold
    thousands, and the browser firing that many is both slow and a good
    way to have half of them rejected.
    """
    applications_crud.get_application_or_404(cursor, application_id)
    records = crud.list_files(cursor, application_id)

    reasons: dict = {}
    queued = 0

    for record in records:
        if isinstance(record.file_extension, str) and not is_deidentifiable(
            record.file_extension
        ):
            reasons["unsupported format"] = reasons.get("unsupported format", 0) + 1
            continue
        if record.deid_status in ("queued", "processing"):
            reasons["already running"] = reasons.get("already running", 0) + 1
            continue

        crud.update_file(
            cursor,
            record.id,
            PatientApplicationFileUpdate(deid_status=queued_status()),
        )
        background.add_task(
            dispatch_deidentification,
            file_id=record.id,
            request_id=request.headers.get("X-Request-ID"),
        )
        queued += 1

    log.info(
        "deid_queued_in_bulk",
        application_id=application_id,
        queued=queued,
        skipped=len(records) - queued,
    )
    return BulkResult(
        total=len(records),
        changed=queued,
        skipped=len(records) - queued,
        reasons=reasons,
    )


@router.post(
    "/applications/{application_id}/files/approve-all",
    response_model=BulkResult,
)
def approve_all_application_files(
    application_id: str,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("application:update")),
):
    """Approve every document still awaiting a decision.

    Files already rejected are left alone: a bulk approve is for clearing
    the undecided pile, not for overturning somebody's verdict.
    """
    applications_crud.get_application_or_404(cursor, application_id)
    records = crud.list_files(cursor, application_id)

    reasons: dict = {}
    approved = 0

    for record in records:
        if record.review_status == "approved":
            reasons["already approved"] = reasons.get("already approved", 0) + 1
            continue
        if record.review_status == "rejected":
            reasons["rejected, left alone"] = (
                reasons.get("rejected, left alone", 0) + 1
            )
            continue

        crud.update_file(
            cursor,
            record.id,
            PatientApplicationFileUpdate(review_status="approved"),
        )
        approved += 1

    log.info(
        "files_approved_in_bulk", application_id=application_id, approved=approved
    )
    return BulkResult(
        total=len(records),
        changed=approved,
        skipped=len(records) - approved,
        reasons=reasons,
    )


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
