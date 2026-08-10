"""Patient application endpoints."""
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Request

from app.audit import record_audit
from app.crud import file_metadata as metadata_crud
from app.crud import patient_application_files as files_crud
from app.crud import patient_applications as crud
from app.crud import patients as patients_crud
from app.db import get_cursor
from app.storage import delete_file as remove_from_disk
from app.submission import finalise_submission
from app.schemas import (
    PatientApplication,
    PatientApplicationCreate,
    PatientApplicationUpdate,
    User,
)
from app.security import require_permission

router = APIRouter(prefix="/applications", tags=["applications"])


def _snapshot(application: PatientApplication) -> dict:
    return application.model_dump(mode="json")


@router.post("", response_model=PatientApplication, status_code=201)
def create_application(
    payload: PatientApplicationCreate,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("application:create")),
):
    patients_crud.get_patient_or_404(cursor, payload.patient_id)

    application = crud.create_application(cursor, payload, actor_id=actor.id)
    background.add_task(
        record_audit,
        action="CREATE",
        entity_type="patient_application",
        entity_id=application.id,
        user_id=actor.id,
        old_values=None,
        new_values=_snapshot(application),
        request_id=request.headers.get("X-Request-ID"),
    )
    return application


@router.get("", response_model=List[PatientApplication])
def list_applications(
    patient_id: Optional[str] = None,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("application:view")),
):
    return crud.list_applications(cursor, patient_id)


@router.get("/{application_id}", response_model=PatientApplication)
def get_application(
    application_id: str,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("application:view")),
):
    return crud.get_application_or_404(cursor, application_id)


@router.put("/{application_id}", response_model=PatientApplication)
def update_application(
    application_id: str,
    payload: PatientApplicationUpdate,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("application:update")),
):
    before = crud.get_application_or_404(cursor, application_id)
    after = crud.update_application(cursor, application_id, payload, actor_id=actor.id)

    if after.status == "submitted" and before.status != "submitted":
        background.add_task(
            finalise_submission,
            application_id=application_id,
            request_id=request.headers.get("X-Request-ID"),
        )

    background.add_task(
        record_audit,
        action="UPDATE",
        entity_type="patient_application",
        entity_id=application_id,
        user_id=actor.id,
        old_values=_snapshot(before),
        new_values=_snapshot(after),
        request_id=request.headers.get("X-Request-ID"),
    )
    return after


@router.delete("/{application_id}", status_code=204)
def delete_application(
    application_id: str,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("application:delete")),
):
    orphaned = files_crud.delete_files_for_application(cursor, application_id)
    metadata_crud.delete_metadata_for_files(cursor, [f.id for f in orphaned])

    deleted = crud.delete_application(cursor, application_id)

    for record in orphaned:
        remove_from_disk(record.file_path)
        if record.de_identified_file_path:
            remove_from_disk(record.de_identified_file_path)

    background.add_task(
        record_audit,
        action="DELETE",
        entity_type="patient_application",
        entity_id=application_id,
        user_id=actor.id,
        old_values=_snapshot(deleted),
        new_values=None,
        request_id=request.headers.get("X-Request-ID"),
    )
