from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, Request

from app.access_log import READ, record_access
from app.audit import record_audit
from app.crud import file_metadata as metadata_crud
from app.crud import patient_application_files as files_crud
from app.crud import patient_applications as applications_crud
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
    actor: User = Depends(require_permission("patient:create")),
):
    patient = crud.create_patient(cursor, payload)
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

    # The detail view is the identified record itself. The list endpoint
    # is deliberately not recorded: it is hit on every page load and
    # would bury the reads that mean something.
    record_access(
        READ,
        actor=actor,
        resource_type="patient",
        resource_id=patient_id,
        patient_id=patient_id,
        identified=True,
    )
    return record


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
    orphaned = []
    for application in applications_crud.list_applications(cursor, patient_id):
        files = files_crud.delete_files_for_application(cursor, application.id)
        metadata_crud.delete_metadata_for_files(cursor, [f.id for f in files])
        orphaned.extend(files)

    applications_crud.delete_applications_for_patient(cursor, patient_id)

    deleted = crud.delete_patient(cursor, patient_id)

    for record in orphaned:
        remove_from_disk(record.file_path)
        if record.de_identified_file_path:
            remove_from_disk(record.de_identified_file_path)

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
