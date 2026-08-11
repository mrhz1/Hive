"""Reading the access trail.

Gated on `log:view`, the same grant as the change trail. Worth knowing
what that grant now carries: this answers "who looked at this patient",
so it is itself sensitive and should be given to reviewers rather than
to everyone who can read an application.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, Query

from app.crud import access_log as crud
from app.db import get_cursor
from app.logging_setup import get_logger
from app.schemas import AccessLog, User
from app.security import require_permission

log = get_logger(__name__)

router = APIRouter(prefix="/access-logs", tags=["access-log"])


@router.get("", response_model=List[AccessLog])
def list_access_logs(
    actor_id: Optional[str] = Query(default=None),
    actor_username: Optional[str] = Query(default=None),
    patient_id: Optional[str] = Query(default=None),
    resource_id: Optional[str] = Query(default=None),
    action: Optional[str] = Query(default=None),
    outcome: Optional[str] = Query(default=None),
    identified_only: bool = Query(default=False),
    date_from: Optional[str] = Query(
        default=None, description="YYYY-MM-DD, inclusive. Reads only these partitions."
    ),
    date_to: Optional[str] = Query(default=None, description="YYYY-MM-DD, inclusive."),
    limit: int = Query(default=100, ge=1, le=1000),
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("log:view")),
):
    """Who saw what, filtered.

    Bound the dates where you can: they select partitions, so a query for
    one week reads one week rather than every day on record.
    """
    return crud.list_access_logs(
        cursor,
        actor_id=actor_id,
        actor_username=actor_username,
        patient_id=patient_id,
        resource_id=resource_id,
        action=action,
        outcome=outcome,
        identified_only=identified_only,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )
