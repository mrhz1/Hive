from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, Request

from app import zone2
from app.audit import record_audit
from app.crud import patients as patients_crud
from app.crud import projects as crud
from app.db import get_cursor
from app.errors import ValidationError
from app.logging_setup import get_logger
from app.project_schemas import (
    Candidate,
    CohortMember,
    CohortUpdate,
    Project,
    ProjectCreate,
    ProjectDetail,
    ProjectRelease,
    ProjectUpdate,
)
from app.schemas import User
from app.security import require_permission

log = get_logger(__name__)

router = APIRouter(prefix="/projects", tags=["projects"])


def _audit(background, request, action, project_id, actor, old=None, new=None):
    background.add_task(
        record_audit,
        action=action,
        entity_type="project",
        entity_id=project_id,
        user_id=actor.id,
        old_values=old,
        new_values=new,
        request_id=request.headers.get("X-Request-ID"),
    )


def _editable(project: Project) -> None:
    if project.status == "in_review":
        raise ValidationError(
            "A release of this project is waiting for review; it can be changed "
            "once the release is approved or rejected"
        )


def _detail(cursor, project: Project) -> ProjectDetail:
    cohort = []
    candidates = {c.patient_id: c for c in zone2.candidates(cursor)}
    for member in crud.list_cohort(cursor, project.id):
        counts = candidates.get(member.patient_id)
        cohort.append(
            CohortMember(
                patient_id=member.patient_id,
                project_patient_id=member.project_patient_id,
                applications=counts.applications if counts else 0,
                documents=counts.documents if counts else 0,
            )
        )
    return ProjectDetail(
        **project.model_dump(),
        cohort=cohort,
        releases=crud.list_releases(cursor, project.id),
    )


@router.get("", response_model=List[Project])
def list_projects(
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("project:view")),
):
    return crud.list_projects(cursor)


@router.get("/candidates", response_model=List[Candidate])
def list_candidates(
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("project:update")),
):
    """Patients with submitted applications, who can be put in a project."""
    return zone2.candidates(cursor)


@router.post("", response_model=ProjectDetail, status_code=201)
def create_project(
    payload: ProjectCreate,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("project:create")),
):
    project = crud.create_project(cursor, payload, actor.id)
    _audit(background, request, "CREATE", project.id, actor, new=project.model_dump(mode="json"))
    return _detail(cursor, project)


@router.get("/{project_id}", response_model=ProjectDetail)
def get_project(
    project_id: str,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("project:view")),
):
    return _detail(cursor, crud.get_project_or_404(cursor, project_id))


@router.put("/{project_id}", response_model=ProjectDetail)
def update_project(
    project_id: str,
    payload: ProjectUpdate,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("project:update")),
):
    before = crud.get_project_or_404(cursor, project_id)
    _editable(before)
    after = crud.update_project(cursor, project_id, payload)
    _audit(
        background, request, "UPDATE", project_id, actor,
        old=before.model_dump(mode="json"), new=after.model_dump(mode="json"),
    )
    return _detail(cursor, after)


@router.put("/{project_id}/cohort", response_model=ProjectDetail)
def set_cohort(
    project_id: str,
    payload: CohortUpdate,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("project:update")),
):
    project = crud.get_project_or_404(cursor, project_id)
    _editable(project)

    wanted = [code.strip().upper() for code in payload.patient_ids if code.strip()]
    known = patients_crud.existing_ids(cursor, wanted)
    unknown = sorted(set(wanted) - set(known))
    if unknown:
        raise ValidationError(f"Unknown patient codes: {', '.join(unknown)}")

    before = [m.patient_id for m in crud.list_cohort(cursor, project_id)]
    after = crud.set_cohort(cursor, project, wanted)
    _audit(
        background, request, "UPDATE", project_id, actor,
        old={"cohort": before}, new={"cohort": [m.patient_id for m in after]},
    )
    return _detail(cursor, project)


@router.delete("/{project_id}", status_code=204)
def delete_project(
    project_id: str,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("project:delete")),
):
    project = crud.get_project_or_404(cursor, project_id)
    if crud.list_releases(cursor, project_id):
        raise ValidationError(
            "This project has releases, so its record and archive are kept"
        )
    crud.delete_project(cursor, project_id)
    _audit(background, request, "DELETE", project_id, actor, old=project.model_dump(mode="json"))


@router.post("/{project_id}/prepare", response_model=ProjectRelease, status_code=201)
def prepare_project(
    project_id: str,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("zone2:prepare")),
):
    """Make the project's safe copy and put it in the Zone 2 inbox."""
    release = zone2.prepare(cursor, project_id, actor.id)
    _audit(
        background, request, "CREATE", project_id, actor,
        new={"release": release.id, "patients": release.patients,
             "applications": release.applications, "documents": release.documents,
             "files_included": release.files_included},
    )
    return release
