from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field

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


# ------------------------------------------------------------ customers


class CustomerCreate(BaseModel):
    email: EmailStr
    first_name: str
    last_name: str
    phone_number: str = Field(min_length=1)
    address: Optional[str] = None
    status: str = "active"
    is_active: bool = True


class CustomerUpdate(BaseModel):
    email: Optional[EmailStr] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = Field(default=None, min_length=1)
    address: Optional[str] = None
    status: Optional[str] = None
    is_active: Optional[bool] = None


class Customer(BaseModel):
    id: str
    email: str
    first_name: str
    last_name: str
    phone_number: str
    address: Optional[str] = None
    status: str
    is_active: bool
    created_at: datetime


# ------------------------------------------------------------ audit log


# -------------------------------------------------------- customer files

DEID_STATUSES = ("pending", "processing", "done", "failed")


class CustomerFile(BaseModel):
    """Metadata for one stored document. The bytes live on disk under
    FILE_STORAGE_DIR; `file_path` points at them."""

    id: str
    customer_id: str
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


class CustomerFileUpdate(BaseModel):
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
    # parsed back to objects on read.
    old_values: Optional[dict] = None
    new_values: Optional[dict] = None
    created_at: datetime
