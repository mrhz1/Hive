import csv
import io
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app import intake, intake_progress
from app.audit import record_audit
from app.crud import intake_files as crud
from app.db import get_cursor
from app.errors import ValidationError
from app.logging_setup import get_logger
from app.schemas import IntakeBatch, IntakeCounts, IntakeFile, User
from app.security import require_permission

log = get_logger(__name__)

router = APIRouter(prefix="/intake", tags=["intake"])

MAX_PAGE_SIZE = 1000
EXPORT_PAGE_SIZE = 5000
EXPORT_COLUMNS = [
    "source_path",
    "status",
    "reason",
    "detail",
    "patient_code",
    "path_code",
    "name_code",
    "file_extension",
    "file_size",
]


class ConflictChoice(BaseModel):
    code: str


class AvailableCode(BaseModel):
    code: str
    files: int
    folder: str
    patient_exists: bool


def _check_status(status):
    if status not in crud.STATUSES:
        raise ValidationError(f"Unknown status '{status}' (known: {', '.join(crud.STATUSES)})")


@router.get("/counts", response_model=IntakeCounts)
def intake_counts(
    batch_id: Optional[str] = None,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("application:view")),
):
    return crud.counts(cursor, batch_id)


@router.get("/codes", response_model=List[AvailableCode])
def intake_codes(
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("application:view")),
):
    return intake.available_codes(cursor)


@router.get("/batches", response_model=List[IntakeBatch])
def intake_batches(
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("application:view")),
):
    return crud.list_batches(cursor)


@router.get("/files", response_model=List[IntakeFile])
def intake_files(
    response: Response,
    status: Optional[str] = None,
    patient_code: Optional[str] = None,
    batch_id: Optional[str] = None,
    limit: int = 500,
    offset: int = 0,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("application:view")),
):
    if status:
        _check_status(status)
    limit = min(max(1, limit), MAX_PAGE_SIZE)
    offset = max(0, offset)

    if status and not patient_code:
        total = crud.status_counts(cursor, batch_id).get(status, 0)
        response.headers["X-Total-Count"] = str(total)
        response.headers["Access-Control-Expose-Headers"] = "X-Total-Count"

    return crud.list_files(
        cursor,
        batch_id=batch_id,
        status=status,
        patient_code=patient_code,
        limit=limit,
        offset=offset,
    )


@router.get("/files/export")
def export_intake_files(
    status: str,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("application:view")),
):
    _check_status(status)

    def generate_csv():
        buffer = io.StringIO()
        csv.writer(buffer).writerow(EXPORT_COLUMNS)
        yield buffer.getvalue()

        offset = 0
        while True:
            files = crud.list_files(cursor, status=status, limit=EXPORT_PAGE_SIZE, offset=offset)
            if not files:
                break
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            for f in files:
                writer.writerow([getattr(f, c) for c in EXPORT_COLUMNS])
            yield buffer.getvalue()
            if len(files) < EXPORT_PAGE_SIZE:
                break
            offset += EXPORT_PAGE_SIZE

    return StreamingResponse(
        generate_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="intake-{status}.csv"'},
    )


@router.post("/files/{file_id}/resolve", response_model=IntakeFile)
def resolve_intake_conflict(
    file_id: str,
    payload: ConflictChoice,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("application:update")),
):
    before = crud.get_file_or_404(cursor, file_id)
    try:
        after = intake.resolve_conflict(cursor, file_id, payload.code)
    except ValueError as e:
        raise ValidationError(str(e)) from e

    background.add_task(
        record_audit,
        action="UPDATE",
        entity_type="intake_file",
        entity_id=file_id,
        user_id=actor.id,
        old_values={
            "status": before.status,
            "path_code": before.path_code,
            "name_code": before.name_code,
        },
        new_values={"status": after.status, "patient_code": after.patient_code},
        request_id=request.headers.get("X-Request-ID"),
    )
    log.info("intake_conflict_resolved", file_id=file_id, code=after.patient_code, actor=actor.id)
    return after


@router.post("/files/{file_id}/retry", response_model=IntakeFile)
def retry_intake_file(
    file_id: str,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("application:update")),
):
    try:
        after = intake.retry(cursor, file_id)
    except ValueError as e:
        raise ValidationError(str(e)) from e
    log.info("intake_file_retried", file_id=file_id, actor=actor.id)
    return after


@router.get("/progress")
def intake_progress_now(
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("application:view")),
):
    return intake_progress.progress(cursor)


@router.get("/progress/batches")
def intake_progress_batches(
    limit: int = 20,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("application:view")),
):
    return intake_progress.batches(cursor, min(max(1, limit), 200))
