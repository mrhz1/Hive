import csv
import io
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Request, Response, UploadFile
from pydantic import BaseModel

from app import followup, redcap
from app.access_log import EXPORT, record_access
from app.audit import record_audit
from app.db import get_cursor
from app.errors import ValidationError
from app.safe_cells import row as safe_row
from app.schemas import User
from app.security import require_permission

router = APIRouter(prefix="/redcap", tags=["redcap"])

MAX_IMPORT_BYTES = 50 * 1024 * 1024


class RedcapStatus(BaseModel):
    mode: str
    datasets: List[redcap.DatasetSummary]


class FollowupSummary(BaseModel):
    automated: int
    manual: int
    not_contacted: int
    sample: List[followup.FollowupRow]


async def _read(file: UploadFile) -> bytes:
    data = await file.read()
    if not data:
        raise ValidationError("The file is empty")
    if len(data) > MAX_IMPORT_BYTES:
        raise ValidationError("The file is larger than 50 MB; split it")
    return data


@router.get("/status", response_model=RedcapStatus)
def status(
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("redcap:view")),
):
    return RedcapStatus(mode=redcap.mode(), datasets=redcap.summaries(cursor))


@router.get("/fields", response_model=List[redcap.Field])
def list_fields(
    dataset: str,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("redcap:view")),
):
    return redcap.fields(cursor, redcap.check_dataset(dataset))


@router.post("/import/preview", response_model=redcap.ImportResult)
async def preview_import(
    kind: str = Form(...),
    dataset: str = Form(...),
    file: UploadFile = File(...),
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("redcap:import")),
):
    return redcap.run_import(cursor, kind, dataset, file.filename or "", await _read(file), False, actor.id)


@router.post("/import", response_model=redcap.ImportResult)
async def run_import(
    background: BackgroundTasks,
    request: Request,
    kind: str = Form(...),
    dataset: str = Form(...),
    file: UploadFile = File(...),
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("redcap:import")),
):
    result = redcap.run_import(cursor, kind, dataset, file.filename or "", await _read(file), True, actor.id)
    background.add_task(
        record_audit,
        action="CREATE",
        entity_type=f"redcap_{result.kind}",
        entity_id=result.dataset,
        user_id=actor.id,
        old_values=None,
        new_values={"file": file.filename, "source": "file", "counts": result.counts},
        request_id=request.headers.get("X-Request-ID"),
    )
    return result


@router.get("/followup", response_model=FollowupSummary)
def followup_summary(
    current_version: Optional[str] = None,
    recent_days: int = followup.RECENT_DAYS,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("redcap:export")),
):
    result = followup.eligibility(cursor, current_version, max(1, recent_days))
    return FollowupSummary(
        automated=len(result.automated),
        manual=len(result.manual),
        not_contacted=len(result.not_contacted),
        sample=(result.automated + result.manual)[:10],
    )


@router.get("/followup/export")
def followup_export(
    current_version: Optional[str] = None,
    recent_days: int = followup.RECENT_DAYS,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("redcap:export")),
):
    result = followup.eligibility(cursor, current_version, max(1, recent_days))
    data = followup.workbook(result, current_version)
    record_access(
        EXPORT, actor=actor, resource_type="followup_list",
        record_count=len(result.automated) + len(result.manual), identified=True,
        detail=f"automated={len(result.automated)} manual={len(result.manual)}",
    )
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="followup-list.xlsx"'},
    )


@router.get("/new-records/export")
def new_records_export(
    dataset: str,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("redcap:export")),
):
    record_field, codes = redcap.patients_without_records(cursor, dataset)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([record_field])
    for code in codes:
        writer.writerow(safe_row([code]))
    record_access(
        EXPORT, actor=actor, resource_type="redcap_new_records", record_count=len(codes),
        identified=False, detail=f"dataset={redcap.check_dataset(dataset)}",
    )
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="new-records-{redcap.check_dataset(dataset)}.csv"'},
    )
