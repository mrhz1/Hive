import hashlib
from pathlib import Path
from typing import Optional

from app.access_log import UPLOAD, record_access
from app.audit import record_audit
from app.logging_setup import get_logger

log = get_logger(__name__)


class _Actor:
    def __init__(self, user_id: Optional[str]):
        self.id = user_id
        self.username = None


def fingerprint(data: bytes) -> dict:
    return {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def file_fingerprint(path) -> Optional[dict]:
    try:
        digest = hashlib.sha256()
        size = 0
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
        return {"size": size, "sha256": digest.hexdigest()}
    except OSError as e:
        log.warning("upload_fingerprint_failed", error=str(e))
        return None


def record_upload(
    *,
    actor=None,
    actor_id: Optional[str] = None,
    kind: str,
    file_id: str,
    stored_name: str,
    uploaded_as: str,
    facts: Optional[dict],
    patient_id: Optional[str] = None,
    application_id: Optional[str] = None,
    identified: bool,
    replaced: Optional[dict] = None,
    request_id: Optional[str] = None,
) -> None:
    actor = actor or _Actor(actor_id)
    new_values = {
        "stored_as": stored_name,
        "uploaded_as": uploaded_as,
        "patient_id": patient_id,
        "application_id": application_id,
        **(facts or {}),
    }
    record_audit(
        action="REPLACE" if replaced else "CREATE",
        entity_type=kind,
        entity_id=file_id,
        user_id=actor.id,
        old_values=replaced,
        new_values=new_values,
        request_id=request_id,
    )
    record_access(
        UPLOAD,
        actor=actor,
        resource_type=kind,
        resource_id=file_id,
        patient_id=patient_id,
        application_id=application_id,
        identified=identified,
        byte_count=(facts or {}).get("size"),
        detail=f"replaced {replaced.get('name')}" if replaced else stored_name,
    )
