from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

PROJECT_STATUSES = ("draft", "in_review", "released", "rejected")
RELEASE_STATUSES = ("in_review", "approved", "rejected")


def _clean(value):
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    approval_reference: Optional[str] = None
    consent_confirmed: bool = False
    documents_approved: bool = False

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A project needs a name")
        return value

    @field_validator("description", "approval_reference", mode="before")
    @classmethod
    def _blank_to_null(cls, value):
        return _clean(value)


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None
    approval_reference: Optional[str] = None
    consent_confirmed: Optional[bool] = None
    documents_approved: Optional[bool] = None

    @field_validator("description", "approval_reference", mode="before")
    @classmethod
    def _blank_to_null(cls, value):
        return _clean(value)


class Project(BaseModel):
    id: str
    short_code: str
    name: str
    description: Optional[str] = None
    approval_reference: Optional[str] = None
    consent_confirmed: bool = False
    documents_approved: bool = False
    status: str = "draft"
    status_reason: Optional[str] = None
    created_by_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    workspace_path: Optional[str] = None
    workspace_built_at: Optional[str] = None
    workspace_expires_at: Optional[str] = None


class ProjectPatient(BaseModel):
    id: str
    project_id: str
    patient_id: str
    project_patient_id: str
    date_shift_days: int
    added_at: Optional[datetime] = None


class ProjectRelease(BaseModel):
    id: str
    project_id: str
    status: str
    status_reason: Optional[str] = None
    prepared_by_id: Optional[str] = None
    prepared_at: Optional[datetime] = None
    reviewed_by_id: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    patients: int = 0
    applications: int = 0
    documents: int = 0
    files_included: bool = False
    archive_path: Optional[str] = None
    inbox_path: Optional[str] = None
    release_path: Optional[str] = None


class CohortMember(BaseModel):
    patient_id: str
    project_patient_id: str
    applications: int = 0
    documents: int = 0


class Candidate(BaseModel):
    patient_id: str
    applications: int
    documents: int
    excluded_reason: Optional[str] = None


class ProjectMember(BaseModel):
    id: str
    project_id: str
    user_id: str
    username: Optional[str] = None
    added_by_id: Optional[str] = None
    added_at: Optional[datetime] = None


class ProjectMemberAdd(BaseModel):
    user_id: str = Field(min_length=1)


class ProjectDetail(Project):
    cohort: List[CohortMember] = Field(default_factory=list)
    releases: List[ProjectRelease] = Field(default_factory=list)
    members: List[ProjectMember] = Field(default_factory=list)


class CohortUpdate(BaseModel):
    patient_ids: List[str]


class ReleaseDecision(BaseModel):
    reason: Optional[str] = None


class ReleaseDocument(BaseModel):
    project_document_id: str
    project_patient_id: str
    file_type: str = ""
    file: str


class ReleaseSummary(ProjectRelease):
    project_name: str = ""
    project_short_code: str = ""
    columns: dict = Field(default_factory=dict)
    samples: dict = Field(default_factory=dict)


PROJECT_CONSENT_TYPES = ("research", "documents")
CONSENT_TYPES = PROJECT_CONSENT_TYPES + ("online_followup",)
CONSENT_STATUSES = ("granted", "refused", "withdrawn")


class ConsentCreate(BaseModel):
    patient_id: str
    consent_type: str = Field(pattern="^(research|documents|online_followup)$")
    status: str = Field(pattern="^(granted|refused|withdrawn)$")
    version: Optional[str] = None
    consent_date: Optional[date] = None
    note: Optional[str] = None

    @field_validator("patient_id", mode="before")
    @classmethod
    def _code(cls, value):
        return (value or "").strip().upper()

    @field_validator("version", "note", mode="before")
    @classmethod
    def _blank_to_null(cls, value):
        return _clean(value)


class Consent(ConsentCreate):
    id: str
    source: Optional[str] = None
    recorded_by_id: Optional[str] = None
    recorded_at: Optional[str] = None


class ConsentImportRow(BaseModel):
    line: int
    code: str = ""
    consent_type: str = ""
    status: str = ""
    action: str
    errors: List[str] = Field(default_factory=list)


class ConsentImportResult(BaseModel):
    applied: bool = False
    counts: dict
    rows: List[ConsentImportRow]


class CohortCriteria(BaseModel):
    prefixes: List[str] = Field(default_factory=list)
    registered_from: Optional[date] = None
    registered_to: Optional[date] = None
    age_min: Optional[int] = Field(default=None, ge=0)
    age_max: Optional[int] = Field(default=None, ge=0)
    countries: List[str] = Field(default_factory=list)
    states: List[str] = Field(default_factory=list)
    institution_codes: List[str] = Field(default_factory=list)
    alive_only: bool = False
    modalities: List[str] = Field(default_factory=list)
    document_from: Optional[date] = None
    document_to: Optional[date] = None
    exclude_codes: List[str] = Field(default_factory=list)


class CohortSearchResult(BaseModel):
    matches: List[str]
    excluded: dict = Field(default_factory=dict)


class WorkspaceBuild(BaseModel):
    include_documents: bool = True


class WorkspaceExtend(BaseModel):
    reason: str = Field(min_length=1)


class WorkspaceDelete(BaseModel):
    reason: Optional[str] = None
