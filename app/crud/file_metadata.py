"""File metadata CRUD, against `file_metadata`."""
import json
import uuid
from typing import List, Optional

from app.db import NOW_SQL, execute
from app.errors import DatabaseError
from app.logging_setup import get_logger
from app.schemas import FileMetadata, FileMetadataCreate

log = get_logger(__name__)

# Order must match sql/schema.sql -- Hive INSERT is positional.
COLUMNS = (
    "id",
    "file_id",
    "file_type",
    "metadata",
    "status",
    "error",
    "created_at",
)

_COLS = ", ".join(f"`{c}`" for c in COLUMNS)

_VALUES = ", ".join(NOW_SQL if c == "created_at" else "%s" for c in COLUMNS)


def _dumps(value: Optional[dict]) -> str:
    """Always a string, never NULL: '{}' is a real answer ("this file carries no metadata") and reads back without a special case."""
    return json.dumps(value or {}, default=str)


def _loads(raw) -> dict:
    if raw is None:
        return {}
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        log.warning("file_metadata_parse_failed", raw=str(raw)[:200])
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _row_to_metadata(row) -> FileMetadata:
    values = dict(zip(COLUMNS, row))
    values["metadata"] = _loads(values["metadata"])
    return FileMetadata(**values)


def create_metadata(cursor, payload: FileMetadataCreate) -> FileMetadata:
    metadata_id = str(uuid.uuid4())

    execute(
        cursor,
        f"INSERT INTO `file_metadata` ({_COLS}) VALUES ({_VALUES})",
        (
            metadata_id,
            payload.file_id,
            payload.file_type,
            _dumps(payload.metadata),
            payload.status,
            payload.error,
        ),
    )
    log.info(
        "file_metadata_created",
        metadata_id=metadata_id,
        file_id=payload.file_id,
        file_type=payload.file_type,
        status=payload.status,
        fields=len(payload.metadata or {}),
    )
    return _get_metadata(cursor, metadata_id)


def _get_metadata(cursor, metadata_id: str) -> FileMetadata:
    execute(
        cursor, f"SELECT {_COLS} FROM `file_metadata` WHERE `id` = %s", (metadata_id,)
    )
    row = cursor.fetchone()
    if row is None:
        raise DatabaseError(f"File metadata '{metadata_id}' not found after insert")
    return _row_to_metadata(row)


def list_metadata(cursor) -> List[FileMetadata]:
    """Every extraction on record, newest first."""
    execute(
        cursor,
        f"SELECT {_COLS} FROM `file_metadata` ORDER BY `created_at` DESC",
    )
    return [_row_to_metadata(r) for r in cursor.fetchall()]


def get_metadata_for_file(cursor, file_id: str) -> Optional[FileMetadata]:
    """The newest row for a file."""
    execute(
        cursor,
        f"SELECT {_COLS} FROM `file_metadata` WHERE `file_id` = %s "
        "ORDER BY `created_at` DESC LIMIT 1",
        (file_id,),
    )
    row = cursor.fetchone()
    return _row_to_metadata(row) if row else None


DEID_KEYS = (
    "deidentified_file_name",
    "deidentified_at",
    "patient_id",
    "deidentified_file_type",
)


def merge_metadata_for_file(cursor, file_id: str, extra: dict) -> Optional[FileMetadata]:
    """Fold extra keys into a file's metadata blob."""
    if not extra:
        return None

    current = get_metadata_for_file(cursor, file_id)
    if current is None:
        log.warning("file_metadata_missing_for_merge", file_id=file_id)
        return None

    merged = {**current.metadata, **{k: v for k, v in extra.items() if v is not None}}

    execute(
        cursor,
        "UPDATE `file_metadata` SET `metadata` = %s WHERE `id` = %s",
        (_dumps(merged), current.id),
    )
    log.info("file_metadata_merged", file_id=file_id, added=sorted(extra))
    return _get_metadata(cursor, current.id)


def delete_metadata_for_files(cursor, file_ids: List[str]) -> None:
    """Removed alongside the files themselves -- Hive has no cascade."""
    if not file_ids:
        return
    placeholders = ", ".join("%s" for _ in file_ids)
    execute(
        cursor,
        f"DELETE FROM `file_metadata` WHERE `file_id` IN ({placeholders})",
        tuple(file_ids),
    )
    log.info("file_metadata_deleted", count=len(file_ids))
