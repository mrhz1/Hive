"""What arrived in the drop folder, and what still needs a person.

Read by the Intake page. The refusals are the point: a skipped file has to
be fixed at source and pushed again, and a conflict has to be decided here,
so both are listed with the full path somebody needs to go and find it.
"""

from typing import List, Optional

import csv
import io

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


class ConflictChoice(BaseModel):
    code: str


@router.get("/counts", response_model=IntakeCounts)
def intake_counts(
    batch_id: Optional[str] = None,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("application:view")),
):
    return crud.counts(cursor, batch_id)


class AvailableCode(BaseModel):
    code: str
    files: int
    folder: str
    patient_exists: bool


@router.get("/codes", response_model=List[AvailableCode])
def intake_codes(
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("application:view")),
):
    """Codes with redacted files nobody has attached yet.

    What an application's patient step picks from. A code whose patient
    already exists selects that patient; one that does not creates it.
    """
    return intake.available_codes(cursor)


@router.get("/batches", response_model=List[IntakeBatch])
def intake_batches(
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("application:view")),
):
    return crud.list_batches(cursor)


MAX_PAGE = 1000


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
    """One page of a status's files.

    Paged because a list is what breaks first at scale: a hundred thousand
    skipped files in one response is a browser that stops responding.
    `X-Total-Count` says how many there are in all.
    """
    if status and status not in crud.STATUSES:
        raise ValidationError(
            f"Unknown status '{status}' (known: {', '.join(crud.STATUSES)})"
        )
    limit = min(max(1, limit), MAX_PAGE)
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


EXPORT_PAGE = 5000
EXPORT_COLUMNS = (
    "source_path", "status", "reason", "detail", "patient_code",
    "path_code", "name_code", "file_extension", "file_size",
)


@router.get("/files/export")
def export_intake_files(
    status: str,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("application:view")),
):
    """Every file of a status as CSV -- the whole list, not a page.

    What goes to whoever owns the source system: full path first, then why.
    Streamed a page at a time, so a hundred thousand rows are never held in
    memory at once.
    """
    if status not in crud.STATUSES:
        raise ValidationError(
            f"Unknown status '{status}' (known: {', '.join(crud.STATUSES)})"
        )

    def rows():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(EXPORT_COLUMNS)
        yield buffer.getvalue()
        offset = 0
        while True:
            page = crud.list_files(cursor, status=status, limit=EXPORT_PAGE, offset=offset)
            if not page:
                return
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            for record in page:
                writer.writerow([getattr(record, c) for c in EXPORT_COLUMNS])
            yield buffer.getvalue()
            if len(page) < EXPORT_PAGE:
                return
            offset += EXPORT_PAGE

    return StreamingResponse(
        rows(),
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
    """Settle a path-vs-name disagreement.

    This is a filing decision -- it says whose document this is -- so it is
    audited like one, with both claims kept in the entry.
    """
    before = crud.get_file_or_404(cursor, file_id)

    try:
        after = intake.resolve_conflict(cursor, file_id, payload.code)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc

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
    log.info(
        "intake_conflict_resolved",
        file_id=file_id,
        code=after.patient_code,
        actor=actor.id,
    )
    return after


@router.post("/files/{file_id}/retry", response_model=IntakeFile)
def retry_intake_file(
    file_id: str,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("application:update")),
):
    """Put a failed file back in the queue, unchanged.

    Picked up by the next automatic run -- within a minute when
    `intake-watch` or the scheduled Job is running.
    """
    try:
        after = intake.retry(cursor, file_id)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    log.info("intake_file_retried", file_id=file_id, actor=actor.id)
    return after


@router.get("/progress")
def intake_progress_now(
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("application:view")),
):
    """How far along, how fast, how long to go, and whether it has stopped."""
    return intake_progress.progress(cursor)


@router.get("/progress/batches")
def intake_progress_batches(
    limit: int = 20,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("application:view")),
):
    """Each push's progress, newest first."""
    return intake_progress.batches(cursor, min(max(1, limit), 200))
