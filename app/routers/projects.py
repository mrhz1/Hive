from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from fastapi.responses import FileResponse

from app import cai_projects, cohort, consent, workspace, workspace_preview, zone2
from app.access_log import READ, record_access
from app.audit import record_audit
from app.crud import patients as patients_crud
from app.crud import projects as crud
from app.crud import users as users_crud
from app.db import authoritative, get_cursor
from app.errors import PermissionDeniedError, ValidationError
from app.logging_setup import get_logger
from app.project_schemas import (
    Candidate,
    CohortCriteria,
    CohortMember,
    CohortSearchResult,
    CohortUpdate,
    Project,
    ProjectCreate,
    ProjectDetail,
    ProjectMember,
    ProjectMemberAdd,
    ProjectRelease,
    ProjectUpdate,
    ReleaseDecision,
    WorkspaceBuild,
    WorkspaceDelete,
    WorkspaceExtend,
    WorkspaceFile,
    WorkspaceTable,
    WorkspaceText,
)
from app.schemas import User
from app.preview import render_dicom_png
from app.security import require_permission
from app.storage import guess_mime_type

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
    if project.status == zone2.ENDED:
        raise ValidationError("This project has ended; it can no longer be changed")
    if project.status == "in_review":
        raise ValidationError(
            "A release of this project is waiting for review; it can be changed "
            "once the release is approved or rejected"
        )


MANAGE = "project:manage"


def _can_open(cursor, project_id: str, actor: User) -> bool:
    return MANAGE in actor.permissions or crud.is_member(cursor, project_id, actor.id)


def _project_for(cursor, project_id: str, actor: User) -> Project:
    project = crud.get_project_or_404(cursor, project_id)
    if not _can_open(cursor, project_id, actor):
        raise PermissionDeniedError("You are not a member of this project")
    return project


def _members(cursor, project_id: str) -> List[ProjectMember]:
    names = {u.id: u.username for u in users_crud.list_users(cursor)}
    found = crud.list_members(cursor, project_id)
    for member in found:
        member.username = names.get(member.user_id)
    return sorted(found, key=lambda m: (m.username or "").lower())


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
        members=_members(cursor, project.id),
    )


@router.get("", response_model=List[Project])
def list_projects(
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("project:view")),
):
    with authoritative(cursor):
        projects = crud.list_projects(cursor)
        if MANAGE in actor.permissions:
            return projects
        mine = crud.member_project_ids(cursor, actor.id)
    return [p for p in projects if p.id in mine]


@router.get("/candidates", response_model=List[Candidate])
def list_candidates(
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("project:update")),
):
    return zone2.candidates(cursor)


@router.get("/{project_id}/candidates", response_model=List[Candidate])
def list_project_candidates(
    project_id: str,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("project:update")),
):
    project = _project_for(cursor, project_id, actor)
    found = zone2.candidates(cursor)
    blocked = consent.excluded(cursor, project, [c.patient_id for c in found])
    return [c.model_copy(update={"excluded_reason": blocked.get(c.patient_id)}) for c in found]


@router.post("/{project_id}/cohort/search", response_model=CohortSearchResult)
def search_cohort(
    project_id: str,
    criteria: CohortCriteria,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("project:update")),
):
    return cohort.search(cursor, _project_for(cursor, project_id, actor), criteria)


@router.post("", response_model=ProjectDetail, status_code=201)
def create_project(
    payload: ProjectCreate,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("project:create")),
):
    project = crud.create_project(cursor, payload, actor.id)
    crud.add_member(cursor, project.id, actor.id, actor.id)
    _audit(background, request, "CREATE", project.id, actor, new=project.model_dump(mode="json"))
    return _detail(cursor, project)


@router.get("/{project_id}", response_model=ProjectDetail)
def get_project(
    project_id: str,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("project:view")),
):
    with authoritative(cursor):
        return _detail(cursor, _project_for(cursor, project_id, actor))


@router.put("/{project_id}", response_model=ProjectDetail)
def update_project(
    project_id: str,
    payload: ProjectUpdate,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("project:update")),
):
    before = _project_for(cursor, project_id, actor)
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
    project = _project_for(cursor, project_id, actor)
    _editable(project)

    wanted = [code.strip().upper() for code in payload.patient_ids if code.strip()]
    known = patients_crud.existing_ids(cursor, wanted)
    unknown = sorted(set(wanted) - set(known))
    if unknown:
        raise ValidationError(f"Unknown patient codes: {', '.join(unknown)}")
    consent.refuse_excluded(cursor, project, wanted)

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
    project = _project_for(cursor, project_id, actor)
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
    _project_for(cursor, project_id, actor)
    release = zone2.prepare(cursor, project_id, actor.id)
    _audit(
        background, request, "CREATE", project_id, actor,
        new={"release": release.id, "patients": release.patients,
             "applications": release.applications, "documents": release.documents,
             "files_included": release.files_included},
    )
    return release


@router.post("/{project_id}/workspace", response_model=ProjectDetail)
def build_workspace(
    project_id: str,
    payload: WorkspaceBuild,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("project:workspace")),
):
    project = workspace.build(cursor, _project_for(cursor, project_id, actor), payload.include_documents)
    _audit(
        background, request, "UPDATE", project_id, actor,
        new={"workspace": "built", "include_documents": payload.include_documents,
             "expires_at": project.workspace_expires_at},
    )
    return _detail(cursor, project)


# Read-only workspace preview (protocol 9.2). Same rule as building it:
# project:workspace and membership of the project. No download route.
WORKSPACE = "project:workspace"


def _workspace_file(cursor, project_id: str, path: str, actor: User):
    with authoritative(cursor):
        project = _project_for(cursor, project_id, actor)
    return workspace_preview.resolve(project, path)


def _looked(actor: User, project_id: str, path: str, records: Optional[int] = None) -> None:
    record_access(
        READ,
        actor=actor,
        resource_type="workspace_file",
        resource_id=f"{project_id}/{path}",
        identified=False,
        record_count=records,
        detail="Zone 1X workspace preview",
    )


@router.get("/{project_id}/workspace/files", response_model=List[WorkspaceFile])
def workspace_files(
    project_id: str,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission(WORKSPACE)),
):
    with authoritative(cursor):
        project = _project_for(cursor, project_id, actor)
    return workspace_preview.list_files(project)


@router.get("/{project_id}/workspace/table", response_model=WorkspaceTable)
def workspace_table(
    project_id: str,
    path: str,
    sheet: Optional[str] = None,
    page: int = 1,
    size: int = 50,
    q: str = "",
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission(WORKSPACE)),
):
    file = _workspace_file(cursor, project_id, path, actor)
    if workspace_preview.kind_of(file) != workspace_preview.TABLE:
        raise ValidationError("Only CSV and Excel files are shown as tables")
    table = workspace_preview.read_table(file, sheet, page, size, q)
    _looked(actor, project_id, path, len(table["rows"]))
    return table


@router.get("/{project_id}/workspace/text", response_model=WorkspaceText)
def workspace_text(
    project_id: str,
    path: str,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission(WORKSPACE)),
):
    file = _workspace_file(cursor, project_id, path, actor)
    if workspace_preview.kind_of(file) != workspace_preview.TEXT:
        raise ValidationError("Only text files are shown as text")
    _looked(actor, project_id, path)
    return workspace_preview.read_text(file)


@router.get("/{project_id}/workspace/content")
def workspace_content(
    project_id: str,
    path: str,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission(WORKSPACE)),
):
    """PDFs and pictures, shown inline by the viewer."""
    file = _workspace_file(cursor, project_id, path, actor)
    if workspace_preview.kind_of(file) not in (workspace_preview.PDF, workspace_preview.IMAGE):
        raise ValidationError("This file type has no preview")
    _looked(actor, project_id, path)
    return FileResponse(
        file,
        media_type=guess_mime_type(file.name, None),
        content_disposition_type="inline",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/{project_id}/workspace/image")
def workspace_image(
    project_id: str,
    path: str,
    frame: int = 0,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission(WORKSPACE)),
):
    """A DICOM file rendered as a PNG, one frame at a time."""
    file = _workspace_file(cursor, project_id, path, actor)
    if workspace_preview.kind_of(file) != workspace_preview.DICOM:
        raise ValidationError("Only DICOM files are rendered as images")
    content, frames = render_dicom_png(file, frame)
    _looked(actor, project_id, path)
    return Response(
        content=content,
        media_type="image/png",
        headers={
            "X-Frame-Count": str(frames),
            "Access-Control-Expose-Headers": "X-Frame-Count",
            "Cache-Control": "no-store",
        },
    )


@router.post("/{project_id}/workspace/extend", response_model=ProjectDetail)
def extend_workspace(
    project_id: str,
    payload: WorkspaceExtend,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("project:workspace")),
):
    reason = payload.reason.strip()
    if not reason:
        raise ValidationError("Say why the workspace is kept longer (the approval)")
    before = _project_for(cursor, project_id, actor)
    after = workspace.extend(cursor, before)
    _audit(
        background, request, "UPDATE", project_id, actor,
        old={"workspace_expires_at": before.workspace_expires_at},
        new={"workspace_expires_at": after.workspace_expires_at, "reason": reason},
    )
    return _detail(cursor, after)


@router.post("/{project_id}/workspace/delete", response_model=ProjectDetail)
def delete_workspace(
    project_id: str,
    payload: WorkspaceDelete,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("project:workspace")),
):
    before = _project_for(cursor, project_id, actor)
    after = workspace.delete(cursor, before)
    _audit(
        background, request, "UPDATE", project_id, actor,
        old={"workspace_path": before.workspace_path},
        new={"workspace": "deleted", "reason": (payload.reason or "").strip() or None},
    )
    return _detail(cursor, after)


@router.post("/{project_id}/end", response_model=ProjectDetail)
def end_project(
    project_id: str,
    payload: ReleaseDecision,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("project:update")),
):
    before = _project_for(cursor, project_id, actor)
    if before.status not in (zone2.ENDED, "in_review") and (payload.reason or "").strip():
        # Researchers lose their Cloudera AI projects first; if a deletion fails,
        # the project stays open so nobody keeps access to an "ended" project.
        cai_projects.end_all_for_project(cursor, project_id, actor.id, "project ended")
    after = zone2.end_project(cursor, project_id, payload.reason)
    _audit(
        background, request, "UPDATE", project_id, actor,
        old={"status": before.status}, new={"status": after.status, "reason": after.status_reason},
    )
    return _detail(cursor, after)


@router.post("/{project_id}/members", response_model=ProjectDetail, status_code=201)
def add_member(
    project_id: str,
    payload: ProjectMemberAdd,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission(MANAGE)),
):
    project = crud.get_project_or_404(cursor, project_id)
    if project.status == zone2.ENDED:
        raise ValidationError("This project has ended; nobody can be added")
    person = users_crud.get_user_or_404(cursor, payload.user_id)
    if not person.is_active:
        raise ValidationError(f"'{person.username}' is not active")
    if crud.is_member(cursor, project_id, person.id):
        raise ValidationError(f"'{person.username}' is already a member")
    crud.add_member(cursor, project_id, person.id, actor.id)
    _audit(background, request, "UPDATE", project_id, actor, new={"member_added": person.username})
    return _detail(cursor, project)


@router.delete("/{project_id}/members/{user_id}", response_model=ProjectDetail)
def remove_member(
    project_id: str,
    user_id: str,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission(MANAGE)),
):
    project = crud.get_project_or_404(cursor, project_id)
    found = [m for m in crud.list_members(cursor, project_id) if m.user_id == user_id]
    if not found:
        raise ValidationError("This person is not a member of the project")
    for member in found:
        crud.remove_member(cursor, member.id)
    person = users_crud.get_user(cursor, user_id)
    _audit(
        background, request, "UPDATE", project_id, actor,
        old={"member_removed": person.username if person else user_id},
    )
    return _detail(cursor, project)
