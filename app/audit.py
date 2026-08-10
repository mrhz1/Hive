"""Fire-and-forget audit recording."""
from typing import Optional

import structlog

from app.crud import audit_log as audit_crud
from app.db import hive_cursor
from app.logging_setup import get_logger
from app.schemas import AuditLogCreate

log = get_logger(__name__)


def record_audit(
    action: str,
    entity_type: str,
    entity_id: str,
    user_id: Optional[str] = None,
    old_values: Optional[dict] = None,
    new_values: Optional[dict] = None,
    request_id: Optional[str] = None,
) -> None:
    """Runs in a background task, i.e."""
    if request_id:
        structlog.contextvars.bind_contextvars(
            request_id=request_id, background_task="record_audit"
        )
    try:
        with hive_cursor() as cursor:
            audit_crud.create_audit_log(
                cursor,
                AuditLogCreate(
                    action=action,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    user_id=user_id,
                    old_values=old_values,
                    new_values=new_values,
                ),
            )
    except Exception as exc:
        log.error(
            "audit_write_failed",
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            error=str(exc),
        )
