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
    because this endpoint is not gated on 'users:update' and must not let
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
    # per-document rows in `patient_files`. Optional here so a partial
    # update need not resend it; PatientCreate makes it required.
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
    status: str = "active"
    is_active: bool = True

    @model_validator(mode="after")
    def _require_an_identifier(self) -> "PatientCreate":
        # Cross-field, so it cannot be expressed as a field constraint --
        # which is also why the 422 reports it against the body rather
        # than against one input.
        if not patient_has_identity(self.model_dump()):
            raise ValueError(PATIENT_IDENTITY_REQUIRED)
        return self


class PatientUpdate(_PatientFields):
    status: Optional[str] = None
    is_active: Optional[bool] = None

    # The identity rule is enforced against the row a partial update
    # would produce, not against the patch alone, so it lives in
    # crud.update_patient where the existing record is in hand.


class Patient(_PatientFields):
    id: str
    status: str
    is_active: bool
    created_at: datetime

    # The read model must not reject a row Hive already holds, so the
    # email columns are plain strings here rather than EmailStr, and the
    # write-side constraints on original_file_path are dropped.
    pemail: Optional[str] = None
    ptemail: Optional[str] = None
    original_file_path: Optional[str] = None


# ------------------------------------------------------------ audit log


# --------------------------------------------------------- patient files

DEID_STATUSES = ("pending", "processing", "done", "failed")


class PatientFile(BaseModel):
    """Metadata for one stored document. The bytes live on disk under
    FILE_STORAGE_DIR; `file_path` points at them."""

    id: str
    patient_id: str
    original_file_name: str
    sanitized_file_name: str
    deidentified_file_name: Optional[str] = None
    file_extension: str
    mime_type: str
    file_size: int
    deid_status: str
    is_identified: bool
    created_at: datetime
    description: Optional[str] = None
    file_path: str
    deidentified_file_path: Optional[str] = None


class PatientFileUpdate(BaseModel):
    """Fields the de-identification job (or a user) may set afterwards.

    Deliberately excludes the storage columns written at upload time --
    a caller must not be able to repoint file_path at an arbitrary file.
    """

    description: Optional[str] = None
    deid_status: Optional[str] = Field(default=None, pattern="^(pending|processing|done|failed)$")
    is_identified: Optional[bool] = None
    deidentified_file_name: Optional[str] = None
    deidentified_file_path: Optional[str] = None


class AuditLogCreate(BaseModel):
    action: str = Field(pattern="^(CREATE|UPDATE|DELETE)$")
    entity_type: str
    entity_id: str
    old_values: Optional[dict] = None
    new_values: Optional[dict] = None


class AuditLog(BaseModel):
    id: str
    action: str
    entity_type: str
    entity_id: str
    # Stored in Hive as JSON-serialised STRING (ORC has no JSON type),
    # parsed back to objects on read. Dates/timestamps inside are already
    # strings by the time they land here (model_dump(mode="json")).
    old_values: Optional[dict] = None
    new_values: Optional[dict] = None
    created_at: datetime
