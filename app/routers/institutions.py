"""Sites (institutions) and their contact email (protocol 9.1.2 step 7).

The list joins the institution codes found on patients with the contacts
saved here, so a site without a contact shows up as one to fill in.
"""

from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import BaseModel, EmailStr, Field, field_validator

from app.audit import record_audit
from app.crud import institutions as crud
from app.db import get_cursor
from app.errors import NotFoundError
from app.schemas import User
from app.security import require_permission

router = APIRouter(prefix="/institutions", tags=["institutions"])


class Institution(BaseModel):
    code: str
    name: Optional[str] = None
    contact_email: Optional[str] = None
    patients: int = 0
    updated_by_id: Optional[str] = None
    updated_at: Optional[str] = None


class InstitutionSave(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    contact_email: Optional[EmailStr] = None

    @field_validator("name", "contact_email", mode="before")
    @classmethod
    def _blank(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


@router.get("", response_model=List[Institution])
def list_institutions(
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("institution:view")),
):
    saved = {crud.normalise(r["code"]): r for r in crud.list_institutions(cursor)}
    counts = crud.patient_counts(cursor)
    out = []
    for code in sorted(set(saved) | set(counts)):
        row = saved.get(code, {"code": code})
        out.append(Institution(**{**row, "code": code, "patients": counts.get(code, 0)}))
    return out


@router.put("/{code}", response_model=Institution)
def save_institution(
    code: str,
    payload: InstitutionSave,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("institution:manage")),
):
    key = crud.normalise(code)
    if not key:
        raise NotFoundError("An institution needs a code")
    before = crud.get(cursor, key)
    after = crud.save(cursor, key, payload.name, payload.contact_email, actor.id)
    background.add_task(
        record_audit,
        action="UPDATE" if before else "CREATE",
        entity_type="institution",
        entity_id=key,
        user_id=actor.id,
        old_values=before,
        new_values=after,
        request_id=request.headers.get("X-Request-ID"),
    )
    return Institution(**after, patients=crud.patient_counts(cursor).get(key, 0))


@router.delete("/{code}", status_code=204)
def delete_institution(
    code: str,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    actor: User = Depends(require_permission("institution:manage")),
):
    before = crud.get(cursor, code)
    if not before:
        raise NotFoundError("No contact is saved for this institution")
    crud.delete(cursor, code)
    background.add_task(
        record_audit,
        action="DELETE",
        entity_type="institution",
        entity_id=before["code"],
        user_id=actor.id,
        old_values=before,
        new_values=None,
        request_id=request.headers.get("X-Request-ID"),
    )
