import csv
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from app import abstraction, cleaning, consent, profiling, redcap, storage, zone2
from app.crud import patients as patients_crud
from app.crud import projects as crud
from app.errors import ValidationError
from app.logging_setup import get_logger
from app.project_schemas import Project
from app.purge import is_deleted_file

log = get_logger(__name__)

PATIENT_COLUMNS = [
    "patient_id", "project_patient_id", "date_of_birth", "registration_date",
    "death_date", "state", "country", "institution_code",
]
APPLICATION_COLUMNS = ["application_id", "patient_id", "status", "created_at", "submitted_at"]
DOCUMENT_COLUMNS = [
    "file_id", "application_id", "patient_id", "file", "file_type", "modality",
    "document_date", "redaction", "leaded_phi", "file_size_bytes",
]

README = """Zone 1X workspace for project {name} ({code}), built {built}.

patients.csv       the cohort: CHSS code, project ID, dates, place
applications.csv   their submitted applications
documents.csv      their de-identified documents{documents_note}
redcap_<name>.csv  REDCap data of the cohort, one file per dataset (identifier fields left out)
cleaning_log.csv   the standard cleanup rules applied to the tables
profile.xlsx       missing values, frequencies and outliers of each column

This is Zone 1X: CHSS codes are here, so nothing in this folder may leave
it. Zone 2 gets only what "Prepare safe copy" makes. The workspace is
deleted on {expires} unless it is extended.
"""


def expiry_days() -> int:
    try:
        return max(1, int(os.environ.get("WORKSPACE_EXPIRY_DAYS", "90")))
    except ValueError:
        return 90


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def _parse(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def workspace_dir(project: Project) -> Path:
    return storage.projects_root() / project.short_code / "workspace"


def _iso_date(value) -> str:
    return value.isoformat()[:10] if value else ""


def _write_csv(path: Path, columns: List[str], rows: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    extra = sorted({k for row in rows for k in row} - set(columns))
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns + extra, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _tables(cursor, project: Project, target: Path, include_documents: bool) -> Dict[str, List[dict]]:
    tables: Dict[str, List[dict]] = {"patients": [], "applications": [], "documents": []}
    for member in crud.list_cohort(cursor, project.id):
        patient = patients_crud.get_patient(cursor, member.patient_id)
        if patient is None:
            continue
        tables["patients"].append(
            {
                "patient_id": patient.id,
                "project_patient_id": member.project_patient_id,
                "date_of_birth": _iso_date(patient.dt_b),
                "registration_date": _iso_date(patient.dt_reg),
                "death_date": _iso_date(patient.dt_d),
                "state": patient.ptstate or "",
                "country": patient.ptcountry or "",
                "institution_code": patient.instcode or "",
            }
        )
        for application in zone2._submitted_applications(cursor, patient.id):
            tables["applications"].append(
                {
                    "application_id": application.id,
                    "patient_id": patient.id,
                    "status": application.status,
                    "created_at": _iso_date(application.created_at),
                    "submitted_at": _iso_date(application.submitted_at),
                }
            )
            for record in zone2._documents(cursor, application.id):
                if is_deleted_file(record) or record.review_status == "rejected":
                    continue
                name = record.deidentified_file_name or Path(record.de_identified_file_path).name
                relative = ""
                if include_documents:
                    source = storage.resolve_stored_path(record.de_identified_file_path)
                    if not source.is_file():
                        raise ValidationError(f"'{name}' is missing from disk")
                    folder = target / "documents" / storage.safe_path_segment(patient.id)
                    folder.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, folder / name)
                    relative = f"documents/{folder.name}/{name}"
                tables["documents"].append(
                    {
                        "file_id": record.id,
                        "application_id": application.id,
                        "patient_id": patient.id,
                        "file": relative,
                        "file_type": abstraction.file_type_of(name),
                        "modality": record.modality or "",
                        "document_date": record.document_date or "",
                        "redaction": record.redaction or "",
                        "leaded_phi": "yes" if record.leaded_phi else "",
                        "file_size_bytes": record.file_size,
                    }
                )
    return tables


def _redcap_tables(cursor, codes: List[str]) -> Dict[str, tuple]:
    out = {}
    for dataset in redcap.datasets_with_values(cursor, codes):
        hidden = {f.field_name for f in redcap.fields(cursor, dataset) if f.identifier}
        columns, rows = redcap.wide_rows(cursor, dataset, codes)
        columns = ["patient_id", "event", "instance"] + [
            c for c in columns if c.split("___")[0] not in hidden
        ]
        out[f"redcap_{dataset}"] = (columns, [{c: row.get(c, "") for c in columns} for row in rows])
    return out


def build(cursor, project: Project, include_documents: bool = True) -> Project:
    if project.status == zone2.ENDED:
        raise ValidationError("The project has ended")
    cohort = crud.list_cohort(cursor, project.id)
    if not cohort:
        raise ValidationError("The project has no patients yet")
    consent.refuse_excluded(cursor, project, [m.patient_id for m in cohort])

    target = workspace_dir(project)
    staging = target.with_name("workspace.building")
    abstraction.remove_dir(staging)
    staging.mkdir(parents=True)
    now = _now()
    current = _parse(project.workspace_expires_at) if project.workspace_path else None
    expires = current if current and current > now else now + timedelta(days=expiry_days())
    try:
        tables = _tables(cursor, project, staging, include_documents)
        extra = _redcap_tables(cursor, [m.patient_id for m in cohort])
        tables.update({name: rows for name, (_, rows) in extra.items()})
        tables, cleaning_log = cleaning.apply(tables)
        _write_csv(staging / "patients.csv", PATIENT_COLUMNS, tables["patients"])
        _write_csv(staging / "applications.csv", APPLICATION_COLUMNS, tables["applications"])
        _write_csv(staging / "documents.csv", DOCUMENT_COLUMNS, tables["documents"])
        for name, (columns, _) in extra.items():
            _write_csv(staging / f"{name}.csv", columns, tables[name])
        _write_csv(staging / "cleaning_log.csv", cleaning.LOG_COLUMNS, cleaning_log)
        profiling.write(staging / "profile.xlsx", tables)
        (staging / "README.txt").write_text(
            README.format(
                name=project.name,
                code=project.short_code,
                built=_iso(now)[:16].replace("T", " "),
                expires=_iso(expires)[:10],
                documents_note=(
                    "\ndocuments/         the files, by CHSS code"
                    if include_documents
                    else "\n                   (the files were not copied)"
                ),
            )
        )
        abstraction._make_read_only(staging)
        abstraction.remove_dir(target)
        staging.rename(target)
    except Exception:
        abstraction.remove_dir(staging)
        raise

    log.info(
        "project_workspace_built",
        project_id=project.id,
        patients=len(tables["patients"]),
        documents=len(tables["documents"]),
    )
    return crud.update_project_fields(
        cursor,
        project.id,
        {
            "workspace_path": str(target),
            "workspace_built_at": _iso(now),
            "workspace_expires_at": _iso(expires),
        },
    )


def _require(project: Project) -> None:
    if not project.workspace_path:
        raise ValidationError("The project has no workspace; build it first")


def extend(cursor, project: Project) -> Project:
    _require(project)
    start = max(_parse(project.workspace_expires_at) or _now(), _now())
    return crud.update_project_fields(
        cursor, project.id, {"workspace_expires_at": _iso(start + timedelta(days=expiry_days()))}
    )


def delete(cursor, project: Project) -> Project:
    _require(project)
    abstraction.remove_dir(Path(project.workspace_path))
    log.info("project_workspace_deleted", project_id=project.id)
    return crud.update_project_fields(
        cursor, project.id, {"workspace_path": None, "workspace_expires_at": None}
    )


def is_due(project: Project, now: Optional[datetime] = None) -> bool:
    expires = _parse(project.workspace_expires_at)
    return bool(project.workspace_path and expires and expires <= (now or _now()))


def expire_due(cursor, now: Optional[datetime] = None) -> List[Project]:
    expired = []
    for project in crud.list_projects(cursor):
        if not is_due(project, now):
            continue
        try:
            expired.append(delete(cursor, project))
        except Exception as e:
            log.error("project_workspace_expiry_failed", project_id=project.id, error=str(e))
    return expired
