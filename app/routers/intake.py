import csv
import io
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.safe_cells import row as safe_row
from app import carbon, intake, intake_progress, intake_run
from app.audit import record_audit
from app.cloudera import ClouderaError
from app.db import get_cursor
from app.errors import ConflictError, ValidationError
from app.logging_setup import get_logger, ref
from app.schemas import User
from app.security import require_permission

log = get_logger(__name__)

router = APIRouter(prefix="/intake", tags=["intake"])

MAX_PAGE_SIZE = 1000
EXPORT_COLUMNS = ["full_path", "reason", "detail", "path_code", "name_code", "file_extension", "file_size"]
LISTS = ["failed", "attention"]


class FilePath(BaseModel):
    path: str


class ConflictChoice(BaseModel):
    path: str
    code: str


class AvailableCode(BaseModel):
    code: str
    files: int
    folder: str
    patient_exists: bool


class RedactedFile(BaseModel):
    id: str
    patient_code: str
    output_name: str
    file_name: str
    relative_path: str
    file_extension: str
    file_size: int
    method: str | None = None


def _check_list(kind):
    if kind not in LISTS:
        raise ValidationError(f"Unknown list '{kind}' (known: {', '.join(LISTS)})")


@router.post("/start")
def start_intake(
    actor: User = Depends(require_permission("deidentifier:run")),
):
    if intake_run.is_running():
        raise ConflictError("De-identification is already running")
    if intake_run.pending_start():
        raise ConflictError("De-identification has already been asked to start")
    intake_run.request_start(by=actor.id)
    try:
        started = intake_run.start_in_background()
    except ClouderaError as e:
        intake_run.clear_start_request()
        raise ValidationError(str(e)) from e
    except Exception:
        intake_run.clear_start_request()
        raise
    log.info("intake_started", actor=actor.id)
    return started


@router.post("/stop")
def stop_intake(
    actor: User = Depends(require_permission("deidentifier:run")),
):
    try:
        stopped = intake_run.stop(by=actor.username)
    except ClouderaError as e:
        raise ValidationError(str(e)) from e
    if not stopped["stopped"]:
        raise ConflictError("De-identification is not running")
    log.info("intake_stop_requested", actor=actor.id, processes=stopped["processes"])
    return stopped


@router.get("/status")
def intake_status(
    _actor: User = Depends(require_permission("deidentifier:view")),
):
    return intake_progress.progress()


@router.get("/finished")
def intake_finished(
    limit: int = 500,
    _actor: User = Depends(require_permission("deidentifier:view")),
):
    return intake_progress.finished_files(min(max(1, limit), 2000))


@router.get("/runs")
def intake_runs(
    limit: int = 20,
    _actor: User = Depends(require_permission("deidentifier:view")),
):
    return intake.list_reports(min(max(1, limit), 200))


@router.get("/files")
def list_files(
    response: Response,
    kind: str,
    limit: int = 500,
    offset: int = 0,
    code: Optional[str] = None,
    _actor: User = Depends(require_permission("deidentifier:view")),
):
    _check_list(kind)
    files = intake.filter_by_code(intake.list_problem_files(kind), code)
    limit = min(max(1, limit), MAX_PAGE_SIZE)
    offset = max(0, offset)
    response.headers["X-Total-Count"] = str(len(files))
    response.headers["Access-Control-Expose-Headers"] = "X-Total-Count"
    return files[offset : offset + limit]


@router.get("/files/codes")
def list_file_codes(
    kind: str,
    _actor: User = Depends(require_permission("deidentifier:view")),
):
    _check_list(kind)
    return intake.codes_in(intake.list_problem_files(kind))


@router.get("/files/export")
def export_files(
    kind: str,
    code: Optional[str] = None,
    _actor: User = Depends(require_permission("deidentifier:view")),
):
    _check_list(kind)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(EXPORT_COLUMNS)
    for f in intake.filter_by_code(intake.list_problem_files(kind), code):
        writer.writerow(safe_row([f.get(c) for c in EXPORT_COLUMNS]))
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="intake-{kind}.csv"'},
    )


class RetryAll(BaseModel):
    code: Optional[str] = None


@router.post("/files/retry-all")
def retry_all_files(
    payload: RetryAll,
    background: BackgroundTasks,
    request: Request,
    actor: User = Depends(require_permission("deidentifier:run")),
):
    moved = intake.retry_all_failed(payload.code or None)
    intake_progress.clear_cache()
    background.add_task(
        record_audit,
        action="UPDATE",
        entity_type="intake_file",
        entity_id=payload.code or "all",
        user_id=actor.id,
        old_values={"status": "failed"},
        new_values={"status": "incoming", "files": moved},
        request_id=request.headers.get("X-Request-ID"),
    )
    return {"moved": moved}


@router.post("/files/retry")
def retry_file(
    payload: FilePath,
    actor: User = Depends(require_permission("deidentifier:run")),
):
    try:
        new_path = intake.retry_failed(payload.path)
    except ValueError as e:
        raise ValidationError(str(e)) from e
    intake_progress.clear_cache()
    log.info("intake_file_retried", file_ref=ref(payload.path), actor=actor.id)
    return {"path": new_path}


@router.post("/files/resolve")
def resolve_conflict(
    payload: ConflictChoice,
    background: BackgroundTasks,
    request: Request,
    actor: User = Depends(require_permission("deidentifier:run")),
):
    try:
        new_path = intake.resolve_conflict(payload.path, payload.code)
    except ValueError as e:
        raise ValidationError(str(e)) from e
    intake_progress.clear_cache()

    background.add_task(
        record_audit,
        action="UPDATE",
        entity_type="intake_file",
        entity_id=new_path,
        user_id=actor.id,
        old_values={"status": "conflict"},
        new_values={"patient_code": payload.code.upper()},
        request_id=request.headers.get("X-Request-ID"),
    )
    log.info("intake_conflict_resolved", file_ref=ref(new_path), code=payload.code, actor=actor.id)
    return {"path": new_path}


@router.get("/codes", response_model=List[AvailableCode])
def intake_codes(
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("application:view")),
):
    return intake.available_codes(cursor)


@router.get("/codes/{code}/files", response_model=List[RedactedFile])
def intake_code_files(
    code: str,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("application:view")),
):
    return intake.files_for_code(cursor, code)


class CarbonSelection(BaseModel):
    paths: List[str]


@router.get("/carbon/browse")
def carbon_browse(
    path: str = "",
    _actor: User = Depends(require_permission("deidentifier:run")),
):
    return carbon.list_folder(path)


@router.post("/carbon/check")
def carbon_check(
    payload: CarbonSelection,
    _actor: User = Depends(require_permission("deidentifier:run")),
):
    found = carbon.plan(payload.paths)
    return {"files": found["files"], "bytes": found["bytes"], "skipped": found["skipped"]}


@router.post("/carbon/copy")
def carbon_copy(
    payload: CarbonSelection,
    background: BackgroundTasks,
    request: Request,
    actor: User = Depends(require_permission("deidentifier:run")),
):
    started = carbon.start_copy(payload.paths, by=actor.username)
    background.add_task(
        record_audit,
        action="CREATE",
        entity_type="intake_import",
        entity_id="carbon",
        user_id=actor.id,
        new_values={
            "share": carbon.share(),
            "paths": payload.paths,
            "files": started["total"],
            "bytes": started["bytes_total"],
        },
        request_id=request.headers.get("X-Request-ID"),
    )
    log.info("carbon_copy_started", actor=actor.id, files=started["total"])
    return started


@router.get("/carbon/status")
def carbon_status(
    _actor: User = Depends(require_permission("deidentifier:run")),
):
    return carbon.status()
