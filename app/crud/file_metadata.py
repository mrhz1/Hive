"""File metadata CRUD, against `file_metadata`.

One row per uploaded document, written straight after the file row. The
extracted fields are a JSON object serialised to STRING because ORC/Hive
has no JSON type -- the same convention audit_log.py uses.

HiveQL only: %s paramstyle, backtick identifiers, no
RETURNING/ON CONFLICT/sequences.
"""
import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from app.db import execute
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


def _dumps(value: Optional[dict]) -> str:
    """Always a string, never NULL: '{}' is a real answer ("this file
    carries no metadata") and reads back without a special case.

    Deliberately NOT sort_keys, unlike audit_log.py: the extractor's
    order is meaningful here. DICOM attributes come out in tag order --
    the order the standard defines and anyone reading these files
    expects -- and sorting alphabetically would scatter a study's
    identifiers through its acquisition parameters for no gain.
    """
    return json.dumps(value or {}, default=str)


def _loads(raw) -> dict:
    if raw is None:
        return {}
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        # A row we cannot parse is not worth failing a page render over,
        # but it is worth knowing about.
        log.warning("file_metadata_parse_failed", raw=str(raw)[:200])
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _row_to_metadata(row) -> FileMetadata:
    values = dict(zip(COLUMNS, row))
    values["metadata"] = _loads(values["metadata"])
    return FileMetadata(**values)


def create_metadata(cursor, payload: FileMetadataCreate) -> FileMetadata:
    metadata_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).replace(tzinfo=None)

    execute(
        cursor,
        f"INSERT INTO `file_metadata` ({_COLS}) "
        f"VALUES ({', '.join('%s' for _ in COLUMNS)})",
        (
            metadata_id,
            payload.file_id,
            payload.file_type,
            _dumps(payload.metadata),
            payload.status,
            payload.error,
            created_at.strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    log.info(
        "file_metadata_created",
        metadata_id=metadata_id,
        file_id=payload.file_id,
        file_type=payload.file_type,
        status=payload.status,
        # The values themselves are not logged: document metadata routinely
        # carries patient names (DICOM PatientName, PDF /Author).
        fields=len(payload.metadata or {}),
    )
    return FileMetadata(
        id=metadata_id,
        file_id=payload.file_id,
        file_type=payload.file_type,
        metadata=payload.metadata or {},
        status=payload.status,
        error=payload.error,
        created_at=created_at,
    )


def get_metadata_for_file(cursor, file_id: str) -> Optional[FileMetadata]:
    """The newest row for a file.

    Newest rather than only: re-uploading is not supported today, but a
    second row would otherwise make this non-deterministic, and returning
    the stale one is the worse failure.
    """
    execute(
        cursor,
        f"SELECT {_COLS} FROM `file_metadata` WHERE `file_id` = %s "
        "ORDER BY `created_at` DESC LIMIT 1",
        (file_id,),
    )
    row = cursor.fetchone()
    return _row_to_metadata(row) if row else None


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
