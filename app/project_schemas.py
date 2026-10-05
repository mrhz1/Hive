"""Models for research projects and their Zone 2 releases."""

from datetime import datetime
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
    """A patient in a project, as the project page shows it (Zone 1X only)."""

    patient_id: str
    project_patient_id: str
    applications: int = 0
    documents: int = 0


class Candidate(BaseModel):
    """A patient who has submitted data that can go into a project."""

    patient_id: str
    applications: int
    documents: int


class ProjectDetail(Project):
    cohort: List[CohortMember] = Field(default_factory=list)
    releases: List[ProjectRelease] = Field(default_factory=list)


class CohortUpdate(BaseModel):
    patient_ids: List[str]


class ReleaseDecision(BaseModel):
    reason: Optional[str] = None


class ReleaseSummary(ProjectRelease):
    project_name: str = ""
    project_short_code: str = ""
    columns: dict = Field(default_factory=dict)
    samples: dict = Field(default_factory=dict)
