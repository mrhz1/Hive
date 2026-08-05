from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, Request

from app.audit import record_audit
from app.crud import patient_files as files_crud
from app.crud import patients as crud
from app.storage import delete_file as remove_from_disk
from app.db import get_cursor
from app.schemas import Patient, PatientCreate, PatientUpdate, User
from app.security import require_permission

router = APIRouter(prefix="/patients", tags=["patients"])


def _snapshot(patient: Patient) -> dict:
    return patient.model_dump(mode="json")


@router.post("", response_model=Patient, status_code=201)
def create_patient(
    payload: PatientCreate,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("patients:create")),
):
    patient = crud.create_patient(cursor, payload)
    background.add_task(
        record_audit,
        action="CREATE",
        entity_type="patient",
        entity_id=patient.id,
        old_values=None,
        new_values=_snapshot(patient),
        request_id=request.headers.get("X-Request-ID"),
    )
    return patient


@router.get("", response_model=List[Patient])
def list_patients(
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("patients:read")),
):
    return crud.list_patients(cursor)


@router.get("/{patient_id}", response_model=Patient)
def get_patient(
    patient_id: str,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("patients:read")),
):
    return crud.get_patient_or_404(cursor, patient_id)


@router.put("/{patient_id}", response_model=Patient)
def update_patient(
    patient_id: str,
    payload: PatientUpdate,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("patients:update")),
):
    before = crud.get_patient_or_404(cursor, patient_id)
    after = crud.update_patient(cursor, patient_id, payload)
    background.add_task(
        record_audit,
        action="UPDATE",
        entity_type="patient",
        entity_id=patient_id,
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
    _actor: User = Depends(require_permission("patients:delete")),
):
    # Remove the patient's documents first, so deleting a patient never
    # leaves rows pointing at a patient that no longer exists.
    orphaned = files_crud.delete_files_for_patient(cursor, patient_id)

    deleted = crud.delete_patient(cursor, patient_id)

    for record in orphaned:
        remove_from_disk(record.file_path)
        if record.deidentified_file_path:
            remove_from_disk(record.deidentified_file_path)

    background.add_task(
        record_audit,
        action="DELETE",
        entity_type="patient",
        entity_id=patient_id,
        old_values=_snapshot(deleted),
        new_values=None,
        request_id=request.headers.get("X-Request-ID"),
    )
