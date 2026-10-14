from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, File, Request, Response, UploadFile

from app import patient_import
from app.access_log import READ, record_access
from app.audit import record_audit
from app.crud import patient_applications as applications_crud
from app.crud import patients as crud
from app.db import get_cursor
from app.errors import ConflictError, ValidationError
from app.schemas import Patient, PatientCreate, PatientUpdate, User
from app.security import assert_permission, require_permission

router = APIRouter(prefix="/patients", tags=["patients"])


def _snapshot(patient: Patient) -> dict:
    return patient.model_dump(mode="json")


@router.post("", response_model=Patient, status_code=201)
def create_patient(
    payload: PatientCreate,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("patient:create")),
):
    patient = crud.create_patient(cursor, payload, checked_by=actor.id)
    background.add_task(
        record_audit,
        action="CREATE",
        entity_type="patient",
        entity_id=patient.id,
        user_id=actor.id,
        old_values=None,
        new_values=_snapshot(patient),
        request_id=request.headers.get("X-Request-ID"),
    )
    return patient


MAX_IMPORT_BYTES = 10 * 1024 * 1024


@router.get("/import/template")
def import_template(_actor: User = Depends(require_permission("patient:create"))):
    return Response(
        content=patient_import.template_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="patients-template.csv"'},
    )


async def _read_import(file: UploadFile) -> bytes:
    data = await file.read()
    if not data:
        raise ValidationError("The file is empty")
    if len(data) > MAX_IMPORT_BYTES:
        raise ValidationError("The file is larger than 10 MB; split it")
    return data


@router.post("/import/preview", response_model=patient_import.ImportResult)
async def preview_import(
    file: UploadFile = File(...),
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("patient:create")),
):
    assert_permission(actor, "patient:update")
    data = await _read_import(file)
    result, _new, _fills = patient_import.plan(cursor, file.filename or "", data)
    return result


@router.post("/import", response_model=patient_import.ImportResult)
async def run_import(
    background: BackgroundTasks,
    request: Request,
    file: UploadFile = File(...),
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("patient:create")),
):
    assert_permission(actor, "patient:update")
    data = await _read_import(file)
    result = patient_import.run(cursor, file.filename or "", data)
    background.add_task(
        record_audit,
        action="CREATE",
        entity_type="patient_import",
        entity_id=file.filename or "import",
        user_id=actor.id,
        old_values=None,
        new_values={
            "counts": result.counts,
            "created": [r.code for r in result.rows if r.action == patient_import.CREATE],
            "updated": [r.code for r in result.rows if r.action == patient_import.UPDATE],
        },
        request_id=request.headers.get("X-Request-ID"),
    )
    return result


@router.get("", response_model=List[Patient])
def list_patients(
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("patient:view")),
):
    return crud.list_patients(cursor)


@router.get("/{patient_id}", response_model=Patient)
def get_patient(
    patient_id: str,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("patient:view")),
):
    record = crud.get_patient_or_404(cursor, patient_id)

    record_access(
        READ,
        actor=actor,
        resource_type="patient",
        resource_id=patient_id,
        patient_id=patient_id,
        identified=True,
    )
    return record


@router.post("/{patient_id}/confirm-details", response_model=Patient)
def confirm_patient_details(
    patient_id: str,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("patient:update")),
):
    before = crud.get_patient_or_404(cursor, patient_id)
    after = crud.confirm_details(cursor, patient_id, actor.id)
    background.add_task(
        record_audit,
        action="UPDATE",
        entity_type="patient",
        entity_id=patient_id,
        user_id=actor.id,
        old_values={"details_checked_at": before.details_checked_at},
        new_values={"details_checked_at": after.details_checked_at},
        request_id=request.headers.get("X-Request-ID"),
    )
    return after


@router.put("/{patient_id}", response_model=Patient)
def update_patient(
    patient_id: str,
    payload: PatientUpdate,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("patient:update")),
):
    before = crud.get_patient_or_404(cursor, patient_id)
    after = crud.update_patient(cursor, patient_id, payload)
    background.add_task(
        record_audit,
        action="UPDATE",
        entity_type="patient",
        entity_id=patient_id,
        user_id=actor.id,
        old_values=_snapshot(before),
        new_values=_snapshot(after),
        request_id=request.headers.get("X-Request-ID"),
    )
    return after


@router.delete("/{patient_id}", status_code=204)
def delete_patient(
    patient_id: str,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("patient:delete")),
):
    existing = applications_crud.list_applications(cursor, patient_id)
    if existing:
        raise ConflictError(
            f"This patient has {len(existing)} "
            f"application{'' if len(existing) == 1 else 's'} and cannot be "
            "deleted. Applications are kept as a record even after they "
            "are deleted, so the patient they belong to has to be kept too."
        )

    deleted = crud.delete_patient(cursor, patient_id)

    background.add_task(
        record_audit,
        action="DELETE",
        entity_type="patient",
        entity_id=patient_id,
        user_id=actor.id,
        old_values=_snapshot(deleted),
        new_values=None,
        request_id=request.headers.get("X-Request-ID"),
    )
