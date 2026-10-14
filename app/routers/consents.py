from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Request, Response, UploadFile

from app import consent
from app.access_log import READ, record_access
from app.audit import record_audit
from app.crud import consents as crud
from app.db import get_cursor
from app.errors import ValidationError
from app.project_schemas import Consent, ConsentCreate, ConsentImportResult
from app.schemas import User
from app.security import require_permission

router = APIRouter(prefix="/consents", tags=["consents"])

MAX_IMPORT_BYTES = 10 * 1024 * 1024


@router.get("", response_model=List[Consent])
def list_consents(
    patient_id: Optional[str] = None,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("consent:view")),
):
    code = (patient_id or "").strip().upper() or None
    rows = sorted(crud.list_consents(cursor, code), key=consent._order)
    if code:
        record_access(
            READ, actor=actor, resource_type="consent", resource_id=code,
            patient_id=code, identified=False,
        )
    return rows


@router.post("", response_model=Consent, status_code=201)
def record_consent(
    payload: ConsentCreate,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("consent:update")),
):
    recorded = consent.record(cursor, payload, actor.id)
    background.add_task(
        record_audit,
        action="CREATE",
        entity_type="consent",
        entity_id=recorded.patient_id,
        user_id=actor.id,
        old_values=None,
        new_values=recorded.model_dump(mode="json"),
        request_id=request.headers.get("X-Request-ID"),
    )
    return recorded


@router.get("/import/template")
def import_template(_actor: User = Depends(require_permission("consent:update"))):
    return Response(
        content=consent.template_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="consent-template.csv"'},
    )


async def _read(file: UploadFile) -> bytes:
    data = await file.read()
    if not data:
        raise ValidationError("The file is empty")
    if len(data) > MAX_IMPORT_BYTES:
        raise ValidationError("The file is larger than 10 MB; split it")
    return data


@router.post("/import/preview", response_model=ConsentImportResult)
async def preview_import(
    file: UploadFile = File(...),
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("consent:update")),
):
    return consent.import_file(cursor, file.filename or "", await _read(file), False, actor.id)


@router.post("/import", response_model=ConsentImportResult)
async def run_import(
    background: BackgroundTasks,
    request: Request,
    file: UploadFile = File(...),
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("consent:update")),
):
    result = consent.import_file(cursor, file.filename or "", await _read(file), True, actor.id)
    background.add_task(
        record_audit,
        action="CREATE",
        entity_type="consent_import",
        entity_id=file.filename or "import",
        user_id=actor.id,
        old_values=None,
        new_values={
            "counts": result.counts,
            "added": [
                f"{r.code}:{r.consent_type}:{r.status}" for r in result.rows if r.action == "add"
            ],
        },
        request_id=request.headers.get("X-Request-ID"),
    )
    return result
