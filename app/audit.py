"""Fire-and-forget audit recording.

Audit writes are the textbook case for backgrounding: nothing in the
response depends on them, and on Hive an INSERT costs seconds. Handing
them to FastAPI's BackgroundTasks keeps them off the request's critical
path -- the caller gets their 201 without waiting for the log write.

Trade-off, deliberately taken: the audit write happens after the response
is sent, so a failure cannot fail the request. It is logged loudly instead
of being swallowed. If audit durability ever needs to be guaranteed
transactionally with the change itself, this has to move back inline.
"""
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
    """Runs in a background task, i.e. outside the request's connection.

    request_id is passed explicitly and re-bound because background tasks
    run after the middleware cleared its contextvars -- without this the
    audit line would lose the trace it belongs to.

    user_id is passed explicitly for the same reason, and is optional
    because not every change has an acting user: the de-identification
    job writes results back with nobody in the picture, and attributing
    that to a person would be a lie in an audit table.
    """
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
        # Never re-raise: the response has already gone out, and an audit
        # failure must not surface as a mysterious 500 on an action that
        # actually succeeded.
        log.error(
            "audit_write_failed",
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            error=str(exc),
        )
