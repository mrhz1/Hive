"""Background upload batches.

Uploading a folder of scans is slow, and almost none of the time goes on
the network: it goes on writing the bytes out, on the per-file Hive
INSERT, and on parsing each document for metadata. Holding the HTTP
request open for all of that is what made the wizard feel hung.

So the request does the one thing only it can do -- drain the multipart
body -- and parks each file in a staging folder next to the final
storage. A background task then moves every file into place, records it,
and emails whoever the application is assigned to when the batch is over,
whether it went well or not.

Job state lives in this process, like the de-identification dispatcher's
does. It is progress for a UI to poll, not a record of anything: the
files and their rows are the record, and they are in storage and in Hive.
A restart mid-batch loses the progress bar, not the documents.
"""
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
from app.logging_setup import get_logger
from app.notifications import (
    notify_upload_failed,
    notify_upload_finished,
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

# How many finished jobs to keep answering for. Enough that a browser
# polling every couple of seconds always finds the job it asked about,
# small enough that a long-lived process does not accumulate them.
MAX_REMEMBERED_JOBS = 200

_jobs: "OrderedDict[str, UploadJob]" = OrderedDict()
_staged: Dict[str, List["StagedFile"]] = {}
_lock = threading.Lock()


@dataclass
class StagedFile:
    """One file waiting in staging for the worker to pick up."""

    name: str
    content_type: Optional[str]
    path: Path
    size: int


# --------------------------------------------------------------- staging


def staging_root() -> Path:
    """Inside the storage root, so moving out of it is a rename."""
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
    """Park one uploaded file on disk under a name that cannot collide."""
    directory = staging_dir(job_id)
    directory.mkdir(parents=True, exist_ok=True)

    # The index keeps two files called 'scan.pdf' apart; the original
    # name is carried on the record, not taken from this path.
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
    """Give up on a batch before the worker ever sees it.

    The request rejected it -- too large, or nothing in it -- so the
    caller already knows. This is so the job does not sit in the registry
    claiming to be pending forever.
    """
    _fail_remaining(job_id, reason)
    _set_status(job_id, "failed", error=reason)
    discard_staging(job_id)


def discard_staging(job_id: str) -> None:
    """Whatever is left in staging is rubbish once the job is over."""
    with _lock:
        _staged.pop(job_id, None)

    directory = staging_dir(job_id)
    try:
        shutil.rmtree(directory, ignore_errors=True)
    except Exception as exc:  # pragma: no cover - cleanup is best effort
        log.warning("upload_staging_cleanup_failed", job_id=job_id, error=str(exc))


# ------------------------------------------------------------- registry


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
    """The live object. Callers hold _lock around any mutation."""
    return _jobs.get(job_id)


def register_file(job_id: str, name: str) -> None:
    """Announce a file before the worker has touched it."""
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
    """Where the batch landed. Set once, by the first file to arrive."""
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
    """Nothing else is going to happen to these; say so rather than leave them pending."""
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


# ------------------------------------------------------- storing a file


def known_patient_id(cursor, application) -> Optional[str]:
    """The patient this application belongs to, if they are on file."""
    patient_id = getattr(application, "patient_id", None)
    if not patient_id:
        return None

    return patient_id if patients_crud.get_patient(cursor, patient_id) else None


def record_metadata(cursor, file_id: str, path, extension: str) -> None:
    """Extract and store metadata for one just-stored file."""
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
    """Move one staged file into storage and record it."""
    extension = file_extension(staged.name)
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


# ---------------------------------------------------------- the worker


def run_upload_job(
    job_id: str,
    application_id: str,
    description: Optional[str] = None,
    actor_id: Optional[str] = None,
    received_at: Optional[datetime] = None,
    request_id: Optional[str] = None,
) -> None:
    """Move a staged batch into storage, then tell someone how it went.

    Never raises: it runs detached from any request, so a failure here
    has nowhere to surface except the log and the notification email.
    """
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
        # A Hive outage, most likely -- the per-file handler below catches
        # anything narrower than that.
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
                # One bad file must not cost the rest of the batch.
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
    """Settle the final status and send the email it calls for."""
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
    """Best effort. A batch that worked is not a failure because email is."""
    try:
        with hive_cursor() as cursor:
            recipients = upload_recipients(cursor, application_id, actor_id)
    except Exception as exc:
        log.error("upload_notice_lookup_failed", job_id=job.id, error=str(exc))
        return

    if not recipients:
        return

    try:
        if job.status == "failed":
            notify_upload_failed(recipients, job)
        else:
            notify_upload_finished(recipients, job)
    except Exception as exc:  # pragma: no cover - mailer already swallows
        log.error("upload_notice_failed", job_id=job.id, error=str(exc))
