"""Patient application endpoints."""
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Request

from app.audit import record_audit
from app.crud import file_metadata as metadata_crud
from app.crud import patient_application_files as files_crud
from app.crud import patient_applications as crud
from app.crud import patients as patients_crud
from app.crud import users as users_crud
from app.db import get_cursor
from app.deid import remove_deid_artifacts
from app.storage import delete_file as remove_from_disk, prune_stored_folders
from app.submission import finalise_submission
from app.errors import ValidationError
from app.logging_setup import get_logger
from app.notifications import notify_assigned
from app.schemas import (
    PatientApplication,
    PatientApplicationCreate,
    PatientApplicationUpdate,
    StatusReason,
    User,
)
from app.security import require_permission

log = get_logger(__name__)

router = APIRouter(prefix="/applications", tags=["applications"])

# An already-rejected application is *not* in here: fixing what was
# wrong and finding the next thing wrong is the normal shape of this
# work, and each rejection has to be able to carry its own reason.
NON_REJECTABLE = ("submitted", "deleted")


def _snapshot(application: PatientApplication) -> dict:
    return application.model_dump(mode="json")


def _notify_assignee(
    background: BackgroundTasks,
    cursor,
    assigned_to_id: Optional[str],
    application_id: str,
    actor: User,
) -> None:
    """Email whoever the application has just been handed to.

    The user is resolved here, on the request's cursor, and the sending
    is what goes to the background: the email must not hold up the
    response, and a mail relay having a bad day must not fail an
    assignment that was recorded perfectly well.
    """
    if not assigned_to_id or assigned_to_id == actor.id:
        return

    assignee = users_crud.get_user(cursor, assigned_to_id)
    if assignee is None:
        return

    background.add_task(
        notify_assigned,
        assignee=assignee,
        application_id=application_id,
        assigned_by=actor,
    )


def _assert_assignee_exists(cursor, user_id: Optional[str]) -> None:
    """An application assigned to nobody real would silently stop notifying."""
    if not user_id:
        return
    if users_crud.get_user(cursor, user_id) is not None:
        return

    # Logged with what the lookup actually saw: the id arriving here comes
    # from a <select> built out of GET /users, so a miss means the two
    # disagree -- a stale list in the browser, or a user deleted since it
    # was fetched.
    known = users_crud.list_users(cursor)
    log.warning(
        "assignee_not_found",
        assigned_to_id=user_id,
        users_visible=len(known),
        sample_ids=[user.id for user in known[:5]],
    )
    raise ValidationError(
        f"User '{user_id}' does not exist. If they were on the list a "
        "moment ago, reload the page -- the list may be out of date."
    )


@router.post("", response_model=PatientApplication, status_code=201)
def create_application(
    payload: PatientApplicationCreate,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("application:create")),
):
    patients_crud.get_patient_or_404(cursor, payload.patient_id)
    _assert_assignee_exists(cursor, payload.assigned_to_id)

    application = crud.create_application(cursor, payload, actor_id=actor.id)

    _notify_assignee(background, cursor, application.assigned_to_id, application.id, actor)

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


# The id on the row, and the field the username it resolves to goes in.
_NAMED_IDS = (
    ("assigned_to_id", "assigned_to_username"),
    ("created_by_id", "created_by_username"),
    ("submitted_by_id", "submitted_by_username"),
    ("reviewed_by_id", "reviewed_by_username"),
)


def _with_user_names(cursor, applications: List[PatientApplication]):
    """Put a username against every user id an application carries.

    One pass over the users, not one lookup per row: a list of two
    hundred applications handled by a handful of people would otherwise
    be hundreds of queries to print a few columns.
    """
    wanted = {
        getattr(application, id_field)
        for application in applications
        for id_field, _ in _NAMED_IDS
        if getattr(application, id_field)
    }
    if not wanted:
        return applications

    names = {
        user.id: user.username
        for user in users_crud.list_users(cursor)
        if user.id in wanted
    }
    for application in applications:
        for id_field, name_field in _NAMED_IDS:
            setattr(
                application,
                name_field,
                names.get(getattr(application, id_field)),
            )

    return applications


@router.get("", response_model=List[PatientApplication])
def list_applications(
    patient_id: Optional[str] = None,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("application:view")),
):
    return _with_user_names(cursor, crud.list_applications(cursor, patient_id))


@router.get("/{application_id}", response_model=PatientApplication)
def get_application(
    application_id: str,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("application:view")),
):
    application = crud.get_application_or_404(cursor, application_id)
    return _with_user_names(cursor, [application])[0]


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

    if "assigned_to_id" in payload.model_fields_set:
        _assert_assignee_exists(cursor, payload.assigned_to_id)

    after = crud.update_application(cursor, application_id, payload, actor_id=actor.id)

    # Only on a change. Re-saving an application for some other reason
    # must not email the assignee again about work they already have.
    if after.assigned_to_id and after.assigned_to_id != before.assigned_to_id:
        _notify_assignee(background, cursor, after.assigned_to_id, application_id, actor)

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


@router.post("/{application_id}/reject", response_model=PatientApplication)
def reject_application(
    application_id: str,
    payload: StatusReason,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("application:update")),
):
    """Reject an application, with the reason on the record."""
    before = crud.get_application_or_404(cursor, application_id)

    if before.status in NON_REJECTABLE:
        raise ValidationError(
            f"An application that is '{before.status}' cannot be rejected"
        )

    reason = (payload.reason or "").strip()
    if not reason:
        raise ValidationError("A reason is required when rejecting an application")

    after = crud.update_application(
        cursor,
        application_id,
        PatientApplicationUpdate(status="rejected", status_reason=reason),
        actor_id=actor.id,
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
    reason: Optional[str] = None,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("application:delete")),
):
    """Remove the documents; keep the application as a record of what happened."""
    before = crud.get_application_or_404(cursor, application_id)

    detail = (reason or "").strip()
    if not detail:
        raise ValidationError("A reason is required when deleting an application")

    orphaned = files_crud.delete_files_for_application(cursor, application_id)
    metadata_crud.delete_metadata_for_files(cursor, [f.id for f in orphaned])

    for record in orphaned:
        # Including what the de-identification run left beside the
        # original -- its extracted text and report, which nothing on
        # the row points at. See app/deid.py.
        remove_deid_artifacts(record.file_path)
        remove_from_disk(record.file_path)
        if record.de_identified_file_path:
            remove_from_disk(record.de_identified_file_path)
        prune_stored_folders(record.file_path, record.de_identified_file_path)

    after = crud.update_application(
        cursor,
        application_id,
        PatientApplicationUpdate(status="deleted", status_reason=detail),
        actor_id=actor.id,
    )

    log.info(
        "application_soft_deleted",
        application_id=application_id,
        files_removed=len(orphaned),
    )

    background.add_task(
        record_audit,
        action="DELETE",
        entity_type="patient_application",
        entity_id=application_id,
        user_id=actor.id,
        old_values=_snapshot(before),
        new_values=_snapshot(after),
        request_id=request.headers.get("X-Request-ID"),
    )
