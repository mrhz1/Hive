"""Deleting a patient's data after consent is withdrawn (protocol 6.7).

Staff start it from the consent matrix once the patient's latest research
consent is withdrawn (or refused). `preview` lists what will go; `purge`
does it:

- every document of every application (originals, de-identified copies,
  sidecars, metadata) and the applications themselves (status "deleted");
- the patient's files still waiting in "need attention" or "failed";
- the patient's REDCap values;
- the patient in the cohort of every project that hasn't ended, with the
  project's Zone 1X workspace rebuilt without them (or deleted if nobody is
  left), and any release still waiting for review rejected;
- abstraction folders holding their documents, rebuilt without them (or
  deleted if empty).

What it can't undo: releases already approved to Zone 2 (and the Cloudera AI
projects made from them). Those are listed so the team can tell the
researchers. The patient record itself (code, contacts) and the consent
history are kept, so the withdrawal stays on file and the patient is never
picked again.
"""

import csv
from pathlib import Path
from typing import Dict, List, Optional

from app import abstraction, consent, purge, workspace, zone2
from app.crud import abstraction_folders as folders_crud
from app.crud import patient_application_files as files_crud
from app.crud import patient_applications as applications_crud
from app.crud import patients as patients_crud
from app.crud import projects as projects_crud
from app.db import execute
from app.errors import ValidationError
from app.logging_setup import get_logger
from app.schemas import PatientApplicationUpdate

log = get_logger(__name__)

RESEARCH = "research"


def _code(value: str) -> str:
    return (value or "").strip().upper()


def _decision(cursor, code: str):
    return consent.latest(cursor, code).get(code, {}).get(RESEARCH)


def _redcap_count(cursor, code: str) -> int:
    execute(cursor, "SELECT COUNT(*) FROM `redcap_values` WHERE `patient_id` = %s", (code,))
    row = cursor.fetchone()
    return int(row[0] or 0) if row else 0


def _problem_files(code: str) -> Dict[str, int]:
    from app import intake

    return {
        kind: len(intake.filter_by_code(intake.list_problem_files(kind), code))
        for kind in ("attention", "failed")
    }


def _in_release(release, code: str) -> bool:
    """Whether the patient was in this release, from its archived id map.
    A release without a readable map counts as containing them."""
    from app.blobstore import any_path, open_file

    path = any_path(release.archive_path or "") / "id_map.csv"
    if not release.archive_path or not path.is_file():
        return True
    with open_file(path, "r", newline="", encoding="utf-8") as handle:
        return any((row.get("patient_id") or "").upper() == code for row in csv.DictReader(handle))


def _projects(cursor, code: str) -> List[dict]:
    out = []
    for project in projects_crud.list_projects(cursor):
        cohort = {m.patient_id: m for m in projects_crud.list_cohort(cursor, project.id)}
        if code not in cohort:
            continue
        releases = projects_crud.list_releases(cursor, project.id)
        out.append({
            "id": project.id,
            "short_code": project.short_code,
            "name": project.name,
            "status": project.status,
            "ended": project.status == zone2.ENDED,
            "project_patient_id": cohort[code].project_patient_id,
            "cohort_size": len(cohort),
            "workspace": bool(project.workspace_path),
            "pending_releases": [r.id for r in releases if r.status == "in_review"],
            "released": [r.id for r in releases
                         if r.status == "approved" and _in_release(r, code)],
        })
    return out


def _folders(cursor, file_ids: set) -> List[dict]:
    out = []
    for folder in folders_crud.list_folders(cursor):
        if folder.status != abstraction.ACTIVE:
            continue
        mine = file_ids & set(folders_crud.file_ids(cursor, folder.id))
        if mine:
            out.append({"id": folder.id, "name": folder.name, "documents": len(mine),
                        "total": folder.file_count or 0})
    return out


def preview(cursor, patient_id: str) -> dict:
    code = _code(patient_id)
    patients_crud.get_patient_or_404(cursor, code)
    decision = _decision(cursor, code)
    blocked: Optional[str] = None
    if not decision or decision.status not in consent.BLOCKING:
        blocked = (
            "The patient's latest research consent is not withdrawn or refused. "
            "Record the withdrawal in the consent matrix first."
        )

    applications, file_ids = [], set()
    for application in applications_crud.list_applications(cursor, code):
        if application.status == purge.DELETED:
            continue
        files = [f for f in files_crud.list_files(cursor, application.id)
                 if not purge.is_deleted_file(f)]
        file_ids.update(f.id for f in files)
        applications.append({"id": application.id, "status": application.status,
                             "documents": len(files)})

    return {
        "patient_id": code,
        "consent_status": decision.status if decision else None,
        "consent_date": decision.consent_date.isoformat() if decision and decision.consent_date else None,
        "allowed": blocked is None,
        "blocked_reason": blocked,
        "applications": applications,
        "documents": len(file_ids),
        "problem_files": _problem_files(code),
        "redcap_values": _redcap_count(cursor, code),
        "projects": _projects(cursor, code),
        "abstraction_folders": _folders(cursor, file_ids),
    }


def _purge_documents(cursor, code: str, reason: str, actor_id: str) -> Dict[str, int]:
    files = applications = 0
    for application in applications_crud.list_applications(cursor, code):
        if application.status == purge.DELETED:
            continue
        for record in files_crud.list_files(cursor, application.id):
            if purge.is_deleted_file(record):
                continue
            purge.purge_file(cursor, record, reason)
            files += 1
        applications_crud.update_application(
            cursor, application.id,
            PatientApplicationUpdate(status=purge.DELETED, status_reason=reason),
            actor_id=actor_id,
        )
        applications += 1
    return {"documents": files, "applications": applications}


def _leave_projects(cursor, code: str, projects: List[dict], reason: str, actor_id: str) -> List[dict]:
    done = []
    for entry in projects:
        if entry["ended"]:
            continue
        project = projects_crud.get_project_or_404(cursor, entry["id"])
        for release_id in entry["pending_releases"]:
            zone2.reject(cursor, release_id, actor_id,
                         f"{reason} (a patient withdrew consent; prepare the project again)")
        remaining = [m.patient_id for m in projects_crud.list_cohort(cursor, project.id)
                     if m.patient_id != code]
        projects_crud.set_cohort(cursor, project, remaining)
        workspace_result = None
        project = projects_crud.get_project_or_404(cursor, project.id)
        if project.workspace_path:
            try:
                if remaining:
                    workspace.build(cursor, project)
                    workspace_result = "rebuilt"
                else:
                    workspace.delete(cursor, project)
                    workspace_result = "deleted"
            except Exception as exc:
                # A workspace that still holds the patient must not stay.
                log.error("withdrawal_workspace_rebuild_failed", project_id=project.id, error=str(exc))
                workspace.delete(cursor, project)
                workspace_result = "deleted"
        done.append({"short_code": entry["short_code"], "workspace": workspace_result,
                     "releases_rejected": len(entry["pending_releases"])})
    return done


def _fix_folders(cursor, folders: List[dict], reason: str, actor_id: str) -> List[dict]:
    done = []
    for entry in folders:
        folder = folders_crud.get_folder_or_404(cursor, entry["id"])
        try:
            abstraction.regenerate(cursor, folder)
            done.append({"name": entry["name"], "result": "rebuilt"})
        except ValidationError:
            abstraction.delete(cursor, folder, actor_id, reason)
            done.append({"name": entry["name"], "result": "deleted"})
    return done


def purge_patient(cursor, patient_id: str, reason: str, actor_id: str) -> dict:
    text = (reason or "").strip()
    if not text:
        raise ValidationError("A reason is required to delete a patient's data")
    before = preview(cursor, patient_id)
    if not before["allowed"]:
        raise ValidationError(before["blocked_reason"])
    code = before["patient_id"]
    note = f"Consent withdrawn: {text}"

    counts = _purge_documents(cursor, code, note, actor_id)
    problems = purge._purge_problem_files(code)
    execute(cursor, "DELETE FROM `redcap_values` WHERE `patient_id` = %s", (code,))
    projects = _leave_projects(cursor, code, before["projects"], note, actor_id)
    folders = _fix_folders(cursor, before["abstraction_folders"], note, actor_id)

    summary = {
        "patient_id": code,
        **counts,
        "problem_files": sum(problems.values()),
        "redcap_values": before["redcap_values"],
        "projects": projects,
        "abstraction_folders": folders,
        "already_released": [
            {"short_code": p["short_code"], "releases": p["released"]}
            for p in before["projects"] if p["released"]
        ],
    }
    log.info("patient_withdrawal_purged", patient_id=code, documents=counts["documents"],
             projects=len(projects))
    return summary
