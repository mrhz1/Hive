from app.access_log import DENIED, record_access
from app.crud import original_grants
from app.crud import patient_applications as applications_crud
from app.errors import PermissionDeniedError
from app.schemas import User
from app.security import assert_permission

ARCHIVED = ("submitted", "approved")
VIEW = "files:view_original"
GRANT = "files:grant_original"


def is_archived(cursor, record) -> bool:
    application = applications_crud.get_application(cursor, record.application_id)
    return bool(application and application.status in ARCHIVED)


def assert_can_view(cursor, actor: User, record) -> None:
    assert_permission(actor, VIEW)
    if not is_archived(cursor, record):
        return
    if original_grants.has_active(cursor, record.id, actor.id):
        return
    record_access(
        DENIED,
        outcome=DENIED,
        actor=actor,
        resource_type="original_file",
        resource_id=record.id,
        application_id=record.application_id,
        identified=True,
        detail="no grant for this archived original",
    )
    raise PermissionDeniedError(
        "This original is archived. The CRS manager has to grant you access to this file first."
    )
