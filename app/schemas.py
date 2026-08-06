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
    """Self-service profile edit (PUT /me).

    Intentionally a subset of UserUpdate: no role_id, status or is_active,
    because this endpoint is not gated on 'user:update' and must not let
    a caller grant themselves a role or reactivate themselves.
    """

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

# Naming follows the source records: `p*` fields are the provider /
# institution the patient is registered with, `pt*` fields are the
# patient's own contact details. fstname/lstname are the patient's name.

# Every optional field an HTML form can submit as an empty string. The
# browser sends '' for a cleared <input>, and '' is not a date, not an
# email and not a meaningful phone number -- normalising it to NULL keeps
# "unknown" as one value in Hive instead of two.
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

# Almost every column may be unknown -- these records are ingested from
# systems that populate very little -- but two things have to hold.
#
# The source document is the reason the record exists, so
# `original_file_path` is mandatory (it is deliberately NOT in the list
# above: a blank must be rejected, not silently turned into NULL).
#
# And a row that nothing can be recognised by is not a record, so at
# least one identifier has to be present. Any one of them will do,
# because the ingested systems disagree about which they populate.
PATIENT_IDENTIFIERS = ("fstname", "lstname", "ptemail")

PATIENT_IDENTITY_REQUIRED = (
    "At least one of fstname, lstname or ptemail is required"
)
PATIENT_FILE_REQUIRED = "original_file_path is required"


def patient_has_identity(values: Mapping[str, Any]) -> bool:
    """True when at least one identifier is populated.

    Takes a mapping rather than a model so the same rule covers a create
    payload and an existing row merged with a partial update.
    """
    return any(str(values.get(name) or "").strip() for name in PATIENT_IDENTIFIERS)


class _PatientFields(BaseModel):
    """Field definitions shared by the create/update payloads.

    Declared once so the two payload models cannot drift, and so a new
    column is added in exactly one place.
    """

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

    # --- patient identity and contact. None of these is required on its
    # own; see PATIENT_IDENTIFIERS for the rule they are bound by.
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

    # --- source documents recorded on the patient itself, alongside the
    # per-document rows in `patient_application_files`. Optional here so a
    # partial update need not resend it; PatientCreate makes it required.
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
        # Whitespace is not a path. Stripping first is what lets
        # min_length=1 reject '   ' the same way it rejects '' -- unlike
        # the optional columns, this one must not become NULL.
        return value.strip() if isinstance(value, str) else value


class PatientCreate(_PatientFields):
    original_file_path: str = Field(min_length=1)

    @model_validator(mode="after")
    def _require_an_identifier(self) -> "PatientCreate":
        # Cross-field, so it cannot be expressed as a field constraint --
        # which is also why the 422 reports it against the body rather
        # than against one input.
        if not patient_has_identity(self.model_dump()):
            raise ValueError(PATIENT_IDENTITY_REQUIRED)
        return self


class PatientUpdate(_PatientFields):
    """Every field optional -- see _PatientFields.

    The identity rule is enforced against the row a partial update would
    produce, not against the patch alone, so it lives in
    crud.update_patient where the existing record is in hand.
    """


class Patient(_PatientFields):
    """A patient record. No status / is_active / created_at: the `patient`
    table holds record data, and lifecycle belongs to the application."""

    id: str

    # The read model must not reject a row Hive already holds, so the
    # email columns are plain strings here rather than EmailStr, and the
    # write-side constraints on original_file_path are dropped.
    pemail: Optional[str] = None
    ptemail: Optional[str] = None
    original_file_path: Optional[str] = None


# ---------------------------------------------- patient application files

# 'pending' and 'queued' are genuinely different facts and collapsing
# them breaks the Cloudera Job backend. A file is 'pending' from the
# moment it is uploaded -- meaning "eligible for a sweep, nobody has
# asked for it yet" -- and 'queued' only once someone pressed the button.
# Without the distinction, either every upload counts as requested, or a
# never-de-identified file cannot be requested at all.
#
# Under DEID_BACKEND=inline the row goes straight to 'processing',
# because the work starts in-process a moment later; 'queued' is the
# state that exists only while a Cloudera Job run is being started and
# has not yet claimed the row.
DEID_STATUSES = ("pending", "queued", "processing", "done", "failed")


class PatientApplicationFile(BaseModel):
    """Metadata for one stored document. The bytes live on disk under
    FILE_STORAGE_DIR; `file_path` points at them.

    Documents hang off an application, not off a patient: a patient's
    files are reached through their applications, which is what makes
    "which submission was this uploaded for?" answerable.

    There is no per-file review verdict. Approval is recorded once, on
    the application (`patient_applications.status`) -- a reviewer accepts
    or rejects a submission, not each page of it.

    Note the two spellings of the redacted-copy columns:
    `deidentified_file_name` against `de_identified_file_path`. That is
    what the Cloudera metastore has; matching it exactly beats being tidy.
    """

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


class PatientApplicationFileUpdate(BaseModel):
    """Fields the de-identification job (or a user) may set afterwards.

    Deliberately excludes the storage columns written at upload time --
    a caller must not be able to repoint file_path at an arbitrary file.
    """

    description: Optional[str] = None
    deid_status: Optional[str] = Field(
        default=None, pattern="^(pending|queued|processing|done|failed)$"
    )
    is_deidentified: Optional[bool] = None
    deidentified_file_name: Optional[str] = None
    de_identified_file_path: Optional[str] = None


# --------------------------------------------------------- file metadata

# What extraction did, kept as a value rather than inferred from an empty
# `metadata` object: "this format carries no metadata" and "we could not
# read it" and "we do not parse this format" are three different answers,
# and the UI should say which.
METADATA_STATUSES = ("ok", "unsupported", "failed")

# The formats app/file_metadata.py knows how to read, by extension.
# Everything else is recorded 'unsupported' -- a row still exists, so the
# UI can distinguish "not extracted" from "never uploaded".
METADATA_EXTENSIONS = {
    "pdf": "pdf",
    "dcm": "dicom",
    "dicom": "dicom",
    "doc": "word",
    "docx": "word",
}


class FileMetadata(BaseModel):
    """Extracted document metadata for one file.

    `metadata` is a free-form object -- a DICOM study and a Word document
    share almost no fields -- stored in Hive as a JSON string and parsed
    back on read, the same convention audit_logs uses.
    """

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


# ------------------------------------------------- patient applications

# 'draft' while the wizard is being filled in, 'submitted' once the user
# hands it over, then a reviewer's verdict.
APPLICATION_STATUSES = ("draft", "submitted", "approved", "rejected")


class PatientApplicationCreate(BaseModel):
    """A new submission for a patient.

    The actor columns (created_by_id / updated_by_id / submitted_by_id /
    reviewed_by_id) and their timestamps are not accepted from the caller
    -- the router stamps them from the authenticated user, so an
    application cannot be attributed to someone who did not act.
    """

    patient_id: str = Field(min_length=1)
    status: str = Field(default="draft", pattern="^(draft|submitted|approved|rejected)$")
    description: Optional[str] = None


class PatientApplicationUpdate(BaseModel):
    status: Optional[str] = Field(
        default=None, pattern="^(draft|submitted|approved|rejected)$"
    )
    description: Optional[str] = None


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


class AuditLogCreate(BaseModel):
    action: str = Field(pattern="^(CREATE|UPDATE|DELETE)$")
    entity_type: str
    entity_id: str
    # The authenticated caller. Optional because not every change has
    # one -- the de-identification job writes results back with no user
    # in the picture, and attributing that to somebody would be a lie.
    user_id: Optional[str] = None
    old_values: Optional[dict] = None
    new_values: Optional[dict] = None


class AuditLog(BaseModel):
    id: str
    action: str
    entity_type: str
    entity_id: str
    user_id: Optional[str] = None
    # Stored in Hive as JSON-serialised STRING (ORC has no JSON type),
    # parsed back to objects on read. Dates/timestamps inside are already
    # strings by the time they land here (model_dump(mode="json")).
    old_values: Optional[dict] = None
    new_values: Optional[dict] = None
    created_at: datetime
