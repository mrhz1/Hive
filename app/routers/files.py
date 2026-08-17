"""The de-identified file library."""
from typing import List, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse

from app.access_log import DOWNLOAD, READ, record_access
from app.audit import record_audit
from app.crud import patient_application_files as crud
from app.crud import patient_applications as applications_crud
from app.crud import patients as patients_crud
from app.db import get_cursor
from app.deid import (
    DEIDENTIFIABLE_LABEL,
    is_deidentifiable,
    remove_deid_artifacts,
)
from app.embed import embed_metadata, generated_facts
from app.errors import NotFoundError, ValidationError
from app.filetype import SNIFF_BYTES, resolve_extension
from app.logging_setup import get_logger
from app.preview import read_word_document, render_dicom_png
from app.schemas import (
    DeidentifiedFile,
    PatientApplicationFileUpdate,
    User,
    WordPreview,
)
from app.security import require_permission
from app.storage import (
    deid_dir_for,
    delete_file as remove_from_disk,
    document_name,
    guess_mime_type,
    resolve_stored_path,
)
from app.ids import new_document_serial

log = get_logger(__name__)

router = APIRouter(prefix="/files-library", tags=["files"])

MAX_FILE_BYTES = 50 * 1024 * 1024


def _patient_index(cursor):
    """application id -> patient id, for labelling rows."""
    return {
        application.id: application.patient_id
        for application in applications_crud.list_applications(cursor)
    }


def _as_library_row(record, patient_id: str) -> DeidentifiedFile:
    return DeidentifiedFile(
        id=record.id,
        application_id=record.application_id,
        patient_id=patient_id,
        name=record.deidentified_file_name or record.sanitized_file_name,
        original_file_name=record.original_file_name,
        file_type=(record.file_extension or "").lower(),
        file_size=record.file_size,
        created_at=record.created_at,
        deid_status=record.deid_status,
        de_identified_file_path=record.de_identified_file_path,
    )


@router.get("", response_model=List[DeidentifiedFile])
def list_deidentified_files(
    patient_id: Optional[str] = None,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("files:read")),
):
    """Every file that has a redacted copy, newest first."""
    patients = _patient_index(cursor)
    rows = [
        _as_library_row(record, patients.get(record.application_id, ""))
        for record in crud.list_files(cursor)
        if record.de_identified_file_path
    ]

    if patient_id:
        rows = [row for row in rows if row.patient_id == patient_id]

    return rows


@router.get("/{file_id}", response_model=DeidentifiedFile)
def get_deidentified_file(
    file_id: str,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("files:read")),
):
    record = crud.get_file_or_404(cursor, file_id)
    if not record.de_identified_file_path:
        raise NotFoundError(f"File '{file_id}' has no de-identified copy")

    patients = _patient_index(cursor)
    return _as_library_row(record, patients.get(record.application_id, ""))


@router.get("/{file_id}/content")
def read_deidentified_file(
    file_id: str,
    download: bool = False,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("files:download")),
):
    """The redacted bytes. Never the original -- this library does not expose it.

    As on the application copy: opening it in the viewer is a read, and
    only `download=true` is a copy leaving.
    """
    record = crud.get_file_or_404(cursor, file_id)
    if not record.de_identified_file_path:
        raise ValidationError("This file has not been de-identified yet")

    path = resolve_stored_path(record.de_identified_file_path)
    if not path.is_file():
        raise ValidationError("The de-identified file is missing from disk")

    _record_library_access(cursor, record, actor, DOWNLOAD if download else READ)

    return FileResponse(
        path,
        media_type=record.mime_type,
        filename=record.deidentified_file_name or path.name,
        content_disposition_type="attachment" if download else "inline",
    )


def _record_library_access(cursor, record, actor, action: str) -> None:
    """This library only ever serves redacted copies, so identified=False."""
    application = applications_crud.get_application(cursor, record.application_id)
    record_access(
        action,
        actor=actor,
        resource_type="deidentified_file",
        resource_id=record.id,
        patient_id=getattr(application, "patient_id", None),
        application_id=record.application_id,
        identified=False,
        byte_count=record.file_size,
        # The name the library lists it under, so the trail and the page
        # call the same file the same thing.
        detail=record.deidentified_file_name or record.sanitized_file_name,
    )


def _redacted_path(cursor, file_id: str):
    """The record, its redacted copy and how to read it. Never the
    original -- this library does not expose it, nor do its previews."""
    record = crud.get_file_or_404(cursor, file_id)
    if not record.de_identified_file_path:
        raise ValidationError("This file has not been de-identified yet")

    path = resolve_stored_path(record.de_identified_file_path)
    if not path.is_file():
        raise ValidationError("The de-identified file is missing from disk")

    extension = (record.file_extension or "").lower()
    return record, path, ("docx" if extension in ("doc", "docx") else extension)


@router.get("/{file_id}/image")
def preview_deidentified_image(
    file_id: str,
    frame: int = 0,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("files:download")),
):
    """One DICOM frame of the redacted copy, as a PNG."""
    record, path, extension = _redacted_path(cursor, file_id)
    if extension not in ("dcm", "dicom"):
        raise ValidationError(f"'{extension}' files are not rendered as images")

    content, frames = render_dicom_png(path, frame)
    # After the render, so a refused or failed request is not recorded as
    # a read that happened.
    _record_library_access(cursor, record, actor, READ)
    return Response(
        content=content,
        media_type="image/png",
        headers={
            "X-Frame-Count": str(frames),
            "Access-Control-Expose-Headers": "X-Frame-Count",
        },
    )


@router.get("/{file_id}/text", response_model=WordPreview)
def preview_deidentified_text(
    file_id: str,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("files:download")),
):
    """The redacted Word document's text."""
    record, path, extension = _redacted_path(cursor, file_id)
    if extension not in ("doc", "docx"):
        raise ValidationError(f"'{extension}' files are not rendered as text")

    document = read_word_document(path)
    _record_library_access(cursor, record, actor, READ)
    return document


async def _read_upload(upload: UploadFile) -> bytes:
    data = await upload.read()
    if not data:
        raise ValidationError("The uploaded file is empty")
    if len(data) > MAX_FILE_BYTES:
        raise ValidationError(
            f"The file is larger than the {MAX_FILE_BYTES // (1024 * 1024)}MB limit"
        )
    return data


def _write_redacted(patient_id: str, extension: str, data: bytes, name: str):
    """Put a manually redacted file straight into its final directory."""
    directory = deid_dir_for(extension)
    directory.mkdir(parents=True, exist_ok=True)

    target = directory / name
    target.write_bytes(data)
    return target


@router.post("", response_model=DeidentifiedFile, status_code=201)
async def upload_deidentified_file(
    background: BackgroundTasks,
    request: Request,
    patient_id: str = Form(...),
    replaces_file_id: Optional[str] = Form(default=None),
    file: UploadFile = File(...),
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("files:upload")),
):
    """Add a manually de-identified file, or replace an existing one."""
    patients_crud.get_patient_or_404(cursor, patient_id)

    raw_name = file.filename or "file"
    data = await _read_upload(file)

    # After the read, not before: an extensionless DICOM is only
    # recognisable from its bytes.
    extension = resolve_extension(raw_name, data[:SNIFF_BYTES])
    if not is_deidentifiable(extension):
        raise ValidationError(
            f"'{extension}' files are not handled here (accepted: "
            f"{DEIDENTIFIABLE_LABEL})"
        )

    if replaces_file_id:
        record = crud.get_file_or_404(cursor, replaces_file_id)
        application = applications_crud.get_application(cursor, record.application_id)
        owner = getattr(application, "patient_id", "")
        if owner != patient_id:
            raise ValidationError(
                "That file belongs to a different patient than the one selected"
            )

        previous = record.de_identified_file_path
        stored = _write_redacted(
            patient_id,
            extension,
            data,
            record.deidentified_file_name or f"{record.id}_deid.{extension}",
        )

        updated = crud.update_file(
            cursor,
            replaces_file_id,
            PatientApplicationFileUpdate(
                deid_status="done",
                is_deidentified=True,
                deidentified_file_name=stored.name,
                de_identified_file_path=str(stored),
            ),
        )

        if previous and previous != str(stored):
            remove_from_disk(previous)

        action = "REPLACE"
        result = updated

    else:
        application = applications_crud.newest_for_patient(cursor, patient_id)
        if application is None:
            raise ValidationError(
                "This patient has no application to attach the file to"
            )

        serial = new_document_serial()
        name = document_name(patient_id, "deid", serial, extension)
        stored = _write_redacted(patient_id, extension, data, name)

        result = crud.create_file(
            cursor,
            application_id=application.id,
            original_file_name=raw_name,
            sanitized_file_name=name,
            file_extension=extension,
            mime_type=guess_mime_type(raw_name, file.content_type),
            file_size=len(data),
            file_path=str(stored),
            description="Manually de-identified upload",
        )
        result = crud.update_file(
            cursor,
            result.id,
            PatientApplicationFileUpdate(
                deid_status="done",
                is_deidentified=True,
                deidentified_file_name=stored.name,
                de_identified_file_path=str(stored),
            ),
        )
        action = "CREATE"

    # Into the file, not into `file_metadata` -- that row is for what the
    # document arrived carrying. See app/embed.py.
    embed_metadata(
        stored,
        extension,
        generated_facts(
            patient_id=patient_id,
            output_name=stored.name,
            output_type=extension,
            by="manual upload",
        ),
    )

    background.add_task(
        record_audit,
        action=action,
        entity_type="deidentified_file",
        entity_id=result.id,
        user_id=actor.id,
        old_values=None,
        new_values={"patient_id": patient_id, "name": stored.name},
        request_id=request.headers.get("X-Request-ID"),
    )

    log.info(
        "deidentified_file_uploaded",
        file_id=result.id,
        patient_id=patient_id,
        replaced=bool(replaces_file_id),
    )
    return _as_library_row(result, patient_id)


@router.delete("/{file_id}", status_code=204)
def delete_deidentified_file(
    file_id: str,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("files:delete")),
):
    """Remove the redacted copy, keeping the original and the row."""
    record = crud.get_file_or_404(cursor, file_id)
    if not record.de_identified_file_path:
        raise NotFoundError(f"File '{file_id}' has no de-identified copy")

    remove_from_disk(record.de_identified_file_path)
    # The rest of that run goes with it: the text and report describe a
    # redaction whose output no longer exists, and the text in
    # particular is the document's contents in the clear. Re-running
    # de-identification writes all three again.
    remove_deid_artifacts(record.file_path)

    crud.update_file(
        cursor,
        file_id,
        PatientApplicationFileUpdate(
            deid_status="pending",
            is_deidentified=False,
            deidentified_file_name=None,
            de_identified_file_path=None,
        ),
    )

    background.add_task(
        record_audit,
        action="DELETE",
        entity_type="deidentified_file",
        entity_id=file_id,
        user_id=actor.id,
        old_values={"name": record.deidentified_file_name},
        new_values=None,
        request_id=request.headers.get("X-Request-ID"),
    )
    return None
