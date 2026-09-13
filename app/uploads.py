import shutil
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import structlog

from app import storage
from app.crud import file_metadata as metadata_crud
from app.crud import patient_application_files as files_crud
from app.crud import patient_applications as applications_crud
from app.crud import patients as patients_crud
from app.db import hive_cursor
from app.file_metadata import extract
from app.filetype import head_of, resolve_extension
from app.logging_setup import get_logger
from app.notifications import (
    notify_upload_failed,
    notify_upload_finished,
    source_folder_for,
    upload_recipients,
)
from app.schemas import FileMetadataCreate, UploadJob, UploadJobFile
from app.storage import (
    file_extension,
    move_file,
    move_patient_document,
    sanitize_filename,
)

log = get_logger(__name__)

STAGING_DIR_NAME = ".uploads"

MAX_REMEMBERED_JOBS = 200

_jobs: "OrderedDict[str, UploadJob]" = OrderedDict()
_staged: Dict[str, List["StagedFile"]] = {}
_lock = threading.Lock()


@dataclass
class StagedFile:

    name: str
    content_type: Optional[str]
    path: Path
    size: int




def staging_root() -> Path:
    return Path(storage.STORAGE_ROOT) / STAGING_DIR_NAME


def staging_dir(job_id: str) -> Path:
    return staging_root() / job_id


def stage(
    job_id: str,
    index: int,
    name: str,
    data: bytes,
    content_type: Optional[str] = None,
) -> StagedFile:
    directory = staging_dir(job_id)
    directory.mkdir(parents=True, exist_ok=True)

    path = directory / f"{index:04d}_{sanitize_filename(name)}"
    path.write_bytes(data)

    staged = StagedFile(
        name=name,
        content_type=content_type,
        path=path,
        size=len(data),
    )
    with _lock:
        _staged.setdefault(job_id, []).append(staged)
    return staged


def abandon_job(job_id: str, reason: str) -> None:
    _fail_remaining(job_id, reason)
    _set_status(job_id, "failed", error=reason)
    discard_staging(job_id)


def discard_staging(job_id: str) -> None:
    with _lock:
        _staged.pop(job_id, None)

    directory = staging_dir(job_id)
    try:
        shutil.rmtree(directory, ignore_errors=True)
    except Exception as exc:  # pragma: no cover - cleanup is best effort
        log.warning("upload_staging_cleanup_failed", job_id=job_id, error=str(exc))




def create_job(application_id: str) -> UploadJob:
    job = UploadJob(
        id=str(uuid.uuid4()),
        application_id=application_id,
        status="pending",
        total=0,
        stored=0,
        failed=0,
        created_at=datetime.now(timezone.utc),
    )
    with _lock:
        _jobs[job.id] = job
        while len(_jobs) > MAX_REMEMBERED_JOBS:
            _jobs.popitem(last=False)
    return job


def get_job(job_id: str) -> Optional[UploadJob]:
    with _lock:
        job = _jobs.get(job_id)
        return job.model_copy(deep=True) if job else None


def _job(job_id: str) -> Optional[UploadJob]:
    return _jobs.get(job_id)


def register_file(job_id: str, name: str) -> None:
    with _lock:
        job = _job(job_id)
        if job is None:
            return
        job.files.append(UploadJobFile(name=name, status="pending"))
        job.total = len(job.files)


def _mark(job_id: str, name: str, status: str, **fields) -> None:
    with _lock:
        job = _job(job_id)
        if job is None:
            return
        for entry in job.files:
            if entry.name == name and entry.status == "pending":
                entry.status = status
                for key, value in fields.items():
                    setattr(entry, key, value)
                break
        job.stored = sum(1 for f in job.files if f.status == "stored")
        job.failed = sum(1 for f in job.files if f.status == "failed")


def _set_folder(job_id: str, path: str) -> None:
    with _lock:
        job = _job(job_id)
        if job is not None and not job.folder:
            job.folder = path


def _set_status(job_id: str, status: str, error: Optional[str] = None) -> None:
    with _lock:
        job = _job(job_id)
        if job is None:
            return
        job.status = status
        if error:
            job.error = error
        if status in ("done", "partial", "failed"):
            job.finished_at = datetime.now(timezone.utc)


def _fail_remaining(job_id: str, reason: str) -> None:
    with _lock:
        job = _job(job_id)
        if job is None:
            return
        for entry in job.files:
            if entry.status == "pending":
                entry.status = "failed"
                entry.error = reason
        job.stored = sum(1 for f in job.files if f.status == "stored")
        job.failed = sum(1 for f in job.files if f.status == "failed")




def known_patient_id(cursor, application) -> Optional[str]:
    patient_id = getattr(application, "patient_id", None)
    if not patient_id:
        return None

    return patient_id if patients_crud.get_patient(cursor, patient_id) else None


def record_metadata(cursor, file_id: str, path, extension: str) -> None:
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


def _store_staged(
    cursor,
    staged: StagedFile,
    *,
    application_id: str,
    patient_id: Optional[str],
    description: Optional[str],
    received_at: datetime,
):
    extension = resolve_extension(staged.name, head_of(staged.path))
    record_id = str(uuid.uuid4())

    if patient_id:
        stored_path = move_patient_document(
            patient_id, extension, staged.path, received_at
        )
        sanitized = stored_path.name
    else:
        sanitized = sanitize_filename(staged.name)
        stored_path = move_file(application_id, record_id, sanitized, staged.path)

    record = files_crud.create_file(
        cursor,
        application_id=application_id,
        original_file_name=staged.name,
        sanitized_file_name=sanitized,
        file_extension=extension,
        mime_type=storage.guess_mime_type(staged.name, staged.content_type),
        file_size=staged.size,
        file_path=str(stored_path),
        description=description,
        file_id=record_id,
    )
    record_metadata(cursor, record.id, stored_path, extension)
    return record




def run_upload_job(
    job_id: str,
    application_id: str,
    description: Optional[str] = None,
    actor_id: Optional[str] = None,
    received_at: Optional[datetime] = None,
    request_id: Optional[str] = None,
) -> None:
    if request_id:
        structlog.contextvars.bind_contextvars(
            request_id=request_id, background_task="run_upload_job"
        )

    received_at = received_at or datetime.now(timezone.utc)

    with _lock:
        items = list(_staged.get(job_id, []))

    _set_status(job_id, "running")

    try:
        _process(
            job_id,
            items,
            application_id=application_id,
            description=description,
            received_at=received_at,
        )
    except Exception as exc:
        log.exception("upload_job_failed", job_id=job_id, error=str(exc))
        _fail_remaining(job_id, str(exc))
        _set_status(job_id, "failed", error=str(exc))
    finally:
        discard_staging(job_id)

    _finish(job_id, application_id, actor_id)


def _process(
    job_id: str,
    items: List[StagedFile],
    *,
    application_id: str,
    description: Optional[str],
    received_at: datetime,
) -> None:
    with hive_cursor() as cursor:
        application = applications_crud.get_application(cursor, application_id)
        patient_id = known_patient_id(cursor, application) if application else None

        for staged in items:
            try:
                record = _store_staged(
                    cursor,
                    staged,
                    application_id=application_id,
                    patient_id=patient_id,
                    description=description,
                    received_at=received_at,
                )
            except Exception as exc:
                log.error(
                    "upload_job_file_failed",
                    job_id=job_id,
                    name=staged.name,
                    error=str(exc),
                )
                _mark(job_id, staged.name, "failed", error=str(exc))
                continue

            _mark(job_id, staged.name, "stored", file_id=record.id)
            _set_folder(job_id, str(Path(record.file_path).parent))


def _finish(job_id: str, application_id: str, actor_id: Optional[str]) -> None:
    job = get_job(job_id)
    if job is None:  # pragma: no cover - only if the job was evicted mid-run
        return

    if job.status != "failed":
        if job.failed and not job.stored:
            _set_status(job_id, "failed")
        elif job.failed:
            _set_status(job_id, "partial")
        else:
            _set_status(job_id, "done")
        job = get_job(job_id) or job

    log.info(
        "upload_job_finished",
        job_id=job_id,
        application_id=application_id,
        status=job.status,
        stored=job.stored,
        failed=job.failed,
    )

    _send_notice(job, application_id, actor_id)


def _send_notice(job: UploadJob, application_id: str, actor_id: Optional[str]) -> None:
    try:
        with hive_cursor() as cursor:
            recipients = upload_recipients(cursor, application_id, actor_id)
            source_folder = source_folder_for(cursor, application_id)
    except Exception as exc:
        log.error("upload_notice_lookup_failed", job_id=job.id, error=str(exc))
        return

    if not recipients:
        return

    try:
        if job.status == "failed":
            notify_upload_failed(recipients, job, source_folder)
        else:
            notify_upload_finished(recipients, job, source_folder)
    except Exception as exc:  # pragma: no cover - mailer already swallows
        log.error("upload_notice_failed", job_id=job.id, error=str(exc))
