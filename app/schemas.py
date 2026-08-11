from datetime import date, datetime
from typing import Any, List, Mapping, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

# ---------------------------------------------------------------- roles


class RoleCreate(BaseModel):
    name: str = Field(min_length=1)
    permissions: List[str] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1)
    permissions: Optional[List[str]] = None


class Role(BaseModel):
    id: str
    name: str
    permissions: List[str]


# ---------------------------------------------------------------- users


class UserCreate(BaseModel):
    username: str = Field(min_length=1)
    email: EmailStr
    first_name: str
    last_name: str
    status: str = "active"
    is_active: bool = True
    role_id: Optional[str] = None


class UserUpdate(BaseModel):
    username: Optional[str] = Field(default=None, min_length=1)
    email: Optional[EmailStr] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    status: Optional[str] = None
    is_active: Optional[bool] = None
    role_id: Optional[str] = None


class ProfileUpdate(BaseModel):
    """Self-service profile edit (PUT /me)."""

    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[EmailStr] = None


class User(BaseModel):
    id: str
    username: str
    email: str
    first_name: str
    last_name: str
    status: str
    is_active: bool
    role_id: Optional[str] = None
    created_at: datetime
    # Denormalised from the roles join so callers get the role inline.
    role_name: Optional[str] = None
    permissions: List[str] = Field(default_factory=list)


# ------------------------------------------------------------- patients


_PATIENT_OPTIONAL_FIELDS = (
    "instcode",
    "pname",
    "pemail",
    "phone1",
    "phone2",
    "wphone1",
    "wphone2",
    "street",
    "street2",
    "street3",
    "city",
    "state",
    "zip",
    "country",
    "ptemail",
    "ptphone",
    "ptphone2",
    "ptwphone",
    "ptwphone2",
    "ptstreet",
    "ptstreet2",
    "ptstreet3",
    "ptcity",
    "ptstate",
    "ptzip",
    "ptcountry",
    "fstname",
    "lstname",
    "dt_reg",
    "dt_b",
    "dt_d",
    "deidentified_file_path",
)

PATIENT_IDENTIFIERS = ("fstname", "lstname", "ptemail")

PATIENT_IDENTITY_REQUIRED = (
    "At least one of fstname, lstname or ptemail is required"
)

# A patient's own source folder is optional: it is a default, and the
# folder that matters belongs to an application (a second application for
# the same patient routinely draws on a different one).
APPLICATION_FILE_REQUIRED = "original_file_path is required"


def patient_has_identity(values: Mapping[str, Any]) -> bool:
    """True when at least one identifier is populated."""
    return any(str(values.get(name) or "").strip() for name in PATIENT_IDENTIFIERS)


class _PatientFields(BaseModel):
    """Field definitions shared by the create/update payloads."""

    # --- provider / institution
    instcode: Optional[str] = None
    pname: Optional[str] = None
    pemail: Optional[EmailStr] = None
    phone1: Optional[str] = None
    phone2: Optional[str] = None
    wphone1: Optional[str] = None
    wphone2: Optional[str] = None
    street: Optional[str] = None
    street2: Optional[str] = None
    street3: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    country: Optional[str] = None

    fstname: Optional[str] = None
    lstname: Optional[str] = None
    ptemail: Optional[EmailStr] = None
    ptphone: Optional[str] = None
    ptphone2: Optional[str] = None
    ptwphone: Optional[str] = None
    ptwphone2: Optional[str] = None
    ptstreet: Optional[str] = None
    ptstreet2: Optional[str] = None
    ptstreet3: Optional[str] = None
    ptcity: Optional[str] = None
    ptstate: Optional[str] = None
    ptzip: Optional[str] = None
    ptcountry: Optional[str] = None

    # --- dates: registration, birth, death
    dt_reg: Optional[date] = None
    dt_b: Optional[date] = None
    dt_d: Optional[date] = None

    original_file_path: Optional[str] = Field(default=None, min_length=1)
    deidentified_file_path: Optional[str] = None

    @field_validator(*_PATIENT_OPTIONAL_FIELDS, mode="before")
    @classmethod
    def _blank_to_null(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("original_file_path", mode="before")
    @classmethod
    def _strip_path(cls, value: Any) -> Any:
        """Whitespace is not a path -- store nothing rather than a blank."""
        if isinstance(value, str):
            return value.strip() or None
        return value


class PatientCreate(_PatientFields):
    @model_validator(mode="after")
    def _require_an_identifier(self) -> "PatientCreate":
        if not patient_has_identity(self.model_dump()):
            raise ValueError(PATIENT_IDENTITY_REQUIRED)
        return self


class PatientUpdate(_PatientFields):
    """Every field optional -- see _PatientFields."""


class Patient(_PatientFields):
    """A patient record."""

    id: str

    pemail: Optional[str] = None
    ptemail: Optional[str] = None
    original_file_path: Optional[str] = None


# ---------------------------------------------- patient application files

DEID_STATUSES = ("pending", "queued", "processing", "done", "failed")


class PatientApplicationFile(BaseModel):
    """Metadata for one stored document."""

    id: str
    application_id: str
    original_file_name: str
    sanitized_file_name: str
    deidentified_file_name: Optional[str] = None
    file_extension: str
    mime_type: str
    file_size: int
    deid_status: str
    is_deidentified: bool
    created_at: datetime
    description: Optional[str] = None
    file_path: str
    de_identified_file_path: Optional[str] = None
    review_status: str = "pending"
    review_note: Optional[str] = None


REVIEW_STATUSES = ("pending", "approved", "rejected")


class FileReview(BaseModel):
    """A reviewer's verdict on one document."""

    review_status: str = Field(pattern="^(approved|rejected)$")
    review_note: Optional[str] = None


class PatientApplicationFileUpdate(BaseModel):
    """Fields the de-identification job (or a user) may set afterwards."""

    description: Optional[str] = None
    deid_status: Optional[str] = Field(
        default=None, pattern="^(pending|queued|processing|done|failed)$"
    )
    is_deidentified: Optional[bool] = None
    deidentified_file_name: Optional[str] = None
    de_identified_file_path: Optional[str] = None
    review_status: Optional[str] = Field(
        default=None, pattern="^(pending|approved|rejected)$"
    )
    review_note: Optional[str] = None


class DeidentifiedFile(BaseModel):
    """One row of the de-identified file library."""

    id: str
    application_id: str
    patient_id: str
    name: str
    original_file_name: str
    file_type: str
    file_size: int
    created_at: datetime
    deid_status: str
    de_identified_file_path: Optional[str] = None


# --------------------------------------------------------- file metadata

METADATA_STATUSES = ("ok", "unsupported", "failed")

METADATA_EXTENSIONS = {
    "pdf": "pdf",
    "dcm": "dicom",
    "dicom": "dicom",
    "doc": "word",
    "docx": "word",
}


class FileMetadata(BaseModel):
    """Extracted document metadata for one file."""

    id: str
    file_id: str
    file_type: str
    metadata: dict = Field(default_factory=dict)
    status: str
    error: Optional[str] = None
    created_at: datetime


class FileMetadataCreate(BaseModel):
    file_id: str
    file_type: str
    metadata: dict = Field(default_factory=dict)
    status: str = Field(pattern="^(ok|unsupported|failed)$")
    error: Optional[str] = None


class FileMetadataRow(FileMetadata):
    """A `file_metadata` row with the document it describes joined on.

    The stored row knows only a file id, which is useless to look at. The
    browse table needs the document's name and whose it is, so the join
    happens once on the way out rather than in every caller.
    """

    file_name: Optional[str] = None
    application_id: Optional[str] = None
    patient_id: Optional[str] = None


# ------------------------------------------------------------- previews


class WordBlock(BaseModel):
    """One paragraph of a Word document, as text rather than markup."""

    kind: str
    style: str
    text: str


class WordPreview(BaseModel):
    blocks: List[WordBlock] = Field(default_factory=list)
    tables: List[List[List[str]]] = Field(default_factory=list)
    truncated: bool = False


# --------------------------------------------------------- upload jobs

UPLOAD_JOB_STATUSES = ("pending", "running", "done", "partial", "failed")


class UploadJobFile(BaseModel):
    """One file's fate within a job."""

    name: str
    status: str = Field(pattern="^(pending|stored|failed)$")
    file_id: Optional[str] = None
    error: Optional[str] = None


class UploadJob(BaseModel):
    """Progress of one background upload batch."""

    id: str
    application_id: str
    status: str
    total: int
    stored: int
    failed: int
    created_at: datetime
    finished_at: Optional[datetime] = None
    error: Optional[str] = None
    # Where the batch landed, once the first file is in place. The wizard
    # records it on the patient as their source folder.
    folder: Optional[str] = None
    files: List[UploadJobFile] = Field(default_factory=list)


# ------------------------------------------------- patient applications

APPLICATION_STATUSES = ("draft", "submitted", "approved", "rejected", "deleted")

_STATUS_PATTERN = "^(draft|submitted|approved|rejected|deleted)$"


class PatientApplicationCreate(BaseModel):
    """A new submission for a patient."""

    patient_id: str = Field(min_length=1)
    status: str = Field(default="draft", pattern=_STATUS_PATTERN)
    description: Optional[str] = None
    # Who is to work on it. Upload notifications go to this user.
    assigned_to_id: Optional[str] = None
    # Where this application's documents came from.
    original_file_path: Optional[str] = None

    @field_validator("assigned_to_id", "original_file_path", mode="before")
    @classmethod
    def _blank_to_null(cls, value: Any) -> Any:
        """An empty <select> means unassigned, not a user whose id is ''."""
        if isinstance(value, str) and not value.strip():
            return None
        return value


class PatientApplicationUpdate(BaseModel):
    status: Optional[str] = Field(default=None, pattern=_STATUS_PATTERN)
    description: Optional[str] = None
    status_reason: Optional[str] = None
    assigned_to_id: Optional[str] = None
    original_file_path: Optional[str] = None

    @field_validator("assigned_to_id", "original_file_path", mode="before")
    @classmethod
    def _blank_to_null(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value


class StatusReason(BaseModel):
    """Why an application is being rejected or deleted."""

    reason: Optional[str] = None


class PatientApplication(BaseModel):
    id: str
    patient_id: str
    submitted_by_id: Optional[str] = None
    reviewed_by_id: Optional[str] = None
    status: str
    description: Optional[str] = None
    created_by_id: Optional[str] = None
    updated_by_id: Optional[str] = None
    submitted_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    reviewed_at: Optional[datetime] = None
    status_reason: Optional[str] = None
    assigned_to_id: Optional[str] = None
    original_file_path: Optional[str] = None


class AuditLogCreate(BaseModel):
    action: str = Field(pattern="^(CREATE|UPDATE|DELETE)$")
    entity_type: str
    entity_id: str
    user_id: Optional[str] = None
    old_values: Optional[dict] = None
    new_values: Optional[dict] = None


class AuditLog(BaseModel):
    id: str
    action: str
    entity_type: str
    entity_id: str
    user_id: Optional[str] = None
    old_values: Optional[dict] = None
    new_values: Optional[dict] = None
    created_at: datetime
