"""Patient file metadata CRUD. HiveQL only: %s paramstyle, backtick
identifiers, STRING types, no RETURNING/ON CONFLICT/sequences.
"""
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from app.db import execute
from app.errors import NotFoundError
from app.logging_setup import get_logger
from app.schemas import PatientFile, PatientFileReview, PatientFileUpdate

log = get_logger(__name__)

_COLS = (
    "`id`, `patient_id`, `original_file_name`, `sanitized_file_name`, "
    "`de_identified_file_name`, `file_extension`, `mime_type`, `file_size`, "
    "`deid_status`, `is_deidentified`, `created_at`, `description`, "
    "`file_path`, `de_identified_file_path`, "
    "`review_status`, `review_description`, `reviewed_by_id`, `reviewed_at`"
)


def _row_to_file(row) -> PatientFile:
    return PatientFile(
        id=row[0],
        patient_id=row[1],
        original_file_name=row[2],
        sanitized_file_name=row[3],
        de_identified_file_name=row[4],
        file_extension=row[5],
        mime_type=row[6],
        file_size=int(row[7]) if row[7] is not None else 0,
        deid_status=row[8],
        is_deidentified=bool(row[9]),
        created_at=row[10],
        description=row[11],
        file_path=row[12],
        de_identified_file_path=row[13],
        # Rows written before the review columns existed read back NULL,
        # which is not a review state the UI knows -- treat it as pending.
        review_status=row[14] or "pending",
        review_description=row[15],
        reviewed_by_id=row[16],
        reviewed_at=row[17],
    )


def create_file(
    cursor,
    *,
    patient_id: str,
    original_file_name: str,
    sanitized_file_name: str,
    file_extension: str,
    mime_type: str,
    file_size: int,
    file_path: str,
    description: Optional[str] = None,
    file_id: Optional[str] = None,
) -> PatientFile:
    """Records an uploaded document.

    Freshly uploaded files are 'pending' and not yet de-identified:
    nothing has been redacted, and claiming otherwise would be a privacy
    lie. They are also unreviewed -- no one has approved them yet.
    """
    new_id = file_id or str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).replace(tzinfo=None)

    execute(
        cursor,
        f"INSERT INTO `patient_files` ({_COLS}) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
        "%s, %s, %s, %s)",
        (
            new_id,
            patient_id,
            original_file_name,
            sanitized_file_name,
            None,  # de_identified_file_name
            file_extension,
            mime_type,
            file_size,
            "pending",
            # A freshly uploaded file has not been through the OCR job,
            # so it is not de-identified until that job says otherwise.
            False,  # is_deidentified
            created_at.strftime("%Y-%m-%d %H:%M:%S"),
            description,
            file_path,
            None,  # de_identified_file_path
            "pending",  # review_status -- nobody has looked at it yet
            None,  # review_description
            None,  # reviewed_by_id
            None,  # reviewed_at
        ),
    )
    log.info(
        "patient_file_created",
        file_id=new_id,
        patient_id=patient_id,
        name=sanitized_file_name,
        bytes=file_size,
    )
    return get_file_or_404(cursor, new_id)


def list_files(cursor, patient_id: Optional[str] = None) -> List[PatientFile]:
    sql = f"SELECT {_COLS} FROM `patient_files`"
    params: tuple = ()
    if patient_id:
        sql += " WHERE `patient_id` = %s"
        params = (patient_id,)
    sql += " ORDER BY `created_at` DESC"

    execute(cursor, sql, params)
    return [_row_to_file(r) for r in cursor.fetchall()]


def get_file(cursor, file_id: str) -> Optional[PatientFile]:
    execute(cursor, f"SELECT {_COLS} FROM `patient_files` WHERE `id` = %s", (file_id,))
    row = cursor.fetchone()
    return _row_to_file(row) if row else None


def get_file_or_404(cursor, file_id: str) -> PatientFile:
    found = get_file(cursor, file_id)
    if found is None:
        raise NotFoundError(f"File '{file_id}' not found")
    return found


def update_file(cursor, file_id: str, payload: PatientFileUpdate) -> PatientFile:
    get_file_or_404(cursor, file_id)

    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        return get_file_or_404(cursor, file_id)

    set_clause = ", ".join(f"`{col}` = %s" for col in fields)
    params = tuple(fields.values()) + (file_id,)
    execute(cursor, f"UPDATE `patient_files` SET {set_clause} WHERE `id` = %s", params)
    log.info("patient_file_updated", file_id=file_id, fields=sorted(fields))
    return get_file_or_404(cursor, file_id)


def review_file(
    cursor, file_id: str, payload: PatientFileReview, reviewer_id: str
) -> PatientFile:
    """Records a reviewer's approve/reject decision on one document.

    The reviewer and the timestamp come from the caller's identity and the
    clock rather than the request body, so a decision cannot be attributed
    to someone who did not make it.
    """
    get_file_or_404(cursor, file_id)
    reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)

    execute(
        cursor,
        "UPDATE `patient_files` SET `review_status` = %s, "
        "`review_description` = %s, `reviewed_by_id` = %s, "
        "`reviewed_at` = CAST(%s AS TIMESTAMP) WHERE `id` = %s",
        (
            payload.review_status,
            payload.review_description,
            reviewer_id,
            reviewed_at.strftime("%Y-%m-%d %H:%M:%S"),
            file_id,
        ),
    )
    log.info(
        "patient_file_reviewed",
        file_id=file_id,
        review_status=payload.review_status,
        reviewer_id=reviewer_id,
    )
    return get_file_or_404(cursor, file_id)


def delete_file(cursor, file_id: str) -> PatientFile:
    existing = get_file_or_404(cursor, file_id)
    execute(cursor, "DELETE FROM `patient_files` WHERE `id` = %s", (file_id,))
    log.info("patient_file_deleted", file_id=file_id)
    return existing


def delete_files_for_patient(cursor, patient_id: str) -> List[PatientFile]:
    """Used when a patient is removed, so their documents do not linger
    as unreachable rows and orphaned bytes."""
    existing = list_files(cursor, patient_id)
    if existing:
        execute(
            cursor,
            "DELETE FROM `patient_files` WHERE `patient_id` = %s",
            (patient_id,),
        )
        log.info(
            "patient_files_deleted", patient_id=patient_id, count=len(existing)
        )
    return existing
