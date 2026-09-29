import uuid
from typing import List, Optional

from app.db import NOW_SQL, execute
from app.errors import NotFoundError
from app.logging_setup import get_logger
from app.schemas import IntakeBatch, IntakeCounts, IntakeFile, IntakeFileUpdate

log = get_logger(__name__)

COLUMNS = (
    "id",
    "batch_id",
    "source_path",
    "relative_path",
    "file_name",
    "file_extension",
    "file_size",
    "checksum",
    "patient_code",
    "path_code",
    "name_code",
    "status",
    "reason",
    "detail",
    "output_path",
    "output_name",
    "claimed_by_file_id",
    "found_at",
    "updated_at",
)

_COLS = ", ".join(f"`{c}`" for c in COLUMNS)

_INSERT_COLUMNS = tuple(c for c in COLUMNS if c not in ("found_at", "updated_at"))

BATCH_COLUMNS = ("id", "root", "status", "started_at", "finished_at")

_BATCH_COLS = ", ".join(f"`{c}`" for c in BATCH_COLUMNS)

STATUSES = (
    "queued",
    "processing",
    "done",
    "failed",
    "skipped",
    "conflict",
    "claimed",
    "submitted",
    "superseded",
)


def _row_to_file(row) -> IntakeFile:
    values = dict(zip(COLUMNS, row))
    values["file_size"] = int(values["file_size"] or 0)
    return IntakeFile(**values)


def _row_to_batch(row) -> IntakeBatch:
    return IntakeBatch(**dict(zip(BATCH_COLUMNS, row)))


def create_batch(cursor, root: str, status: str = "sweeping") -> IntakeBatch:
    batch_id = str(uuid.uuid4())
    execute(
        cursor,
        f"INSERT INTO `intake_batches` ({_BATCH_COLS}) VALUES "
        f"(%s, %s, %s, {NOW_SQL}, CAST(NULL AS TIMESTAMP))",
        (batch_id, root, status),
    )
    log.info("intake_batch_started", batch_id=batch_id, root=root)
    return get_batch_or_404(cursor, batch_id)


def get_batch(cursor, batch_id: str) -> Optional[IntakeBatch]:
    execute(
        cursor,
        f"SELECT {_BATCH_COLS} FROM `intake_batches` WHERE `id` = %s",
        (batch_id,),
    )
    row = cursor.fetchone()
    return _row_to_batch(row) if row else None


def get_batch_or_404(cursor, batch_id: str) -> IntakeBatch:
    batch = get_batch(cursor, batch_id)
    if batch is None:
        raise NotFoundError(f"Intake batch '{batch_id}' not found")
    return batch


def list_batches(cursor) -> List[IntakeBatch]:
    execute(
        cursor,
        f"SELECT {_BATCH_COLS} FROM `intake_batches` ORDER BY `started_at` DESC",
    )
    return [_row_to_batch(r) for r in cursor.fetchall()]


def finish_batch(cursor, batch_id: str, status: str) -> IntakeBatch:
    execute(
        cursor,
        f"UPDATE `intake_batches` SET `status` = %s, `finished_at` = {NOW_SQL} "
        "WHERE `id` = %s",
        (status, batch_id),
    )
    log.info("intake_batch_finished", batch_id=batch_id, status=status)
    return get_batch_or_404(cursor, batch_id)


def get_file(cursor, file_id: str) -> Optional[IntakeFile]:
    execute(
        cursor, f"SELECT {_COLS} FROM `intake_files` WHERE `id` = %s", (file_id,)
    )
    row = cursor.fetchone()
    return _row_to_file(row) if row else None


def get_file_or_404(cursor, file_id: str) -> IntakeFile:
    record = get_file(cursor, file_id)
    if record is None:
        raise NotFoundError(f"Intake file '{file_id}' not found")
    return record


def list_files(
    cursor,
    batch_id: Optional[str] = None,
    status: Optional[str] = None,
    patient_code: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
) -> List[IntakeFile]:
    sql = f"SELECT {_COLS} FROM `intake_files`"

    clauses = []
    params: list = []
    if batch_id:
        clauses.append("`batch_id` = %s")
        params.append(batch_id)
    if status:
        clauses.append("`status` = %s")
        params.append(status)
    if patient_code:
        clauses.append("`patient_code` = %s")
        params.append(patient_code)

    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY `found_at` DESC"
    if limit is not None:
        sql += f" LIMIT {int(limit)} OFFSET {int(offset)}"

    execute(cursor, sql, tuple(params))
    return [_row_to_file(r) for r in cursor.fetchall()]


def oldest_with_status(cursor, status: str) -> Optional[IntakeFile]:
    execute(
        cursor,
        f"SELECT {_COLS} FROM `intake_files` WHERE `status` = %s "
        "ORDER BY `found_at` ASC LIMIT 1",
        (status,),
    )
    row = cursor.fetchone()
    return _row_to_file(row) if row else None


def update_file(cursor, file_id: str, payload: IntakeFileUpdate) -> IntakeFile:
    get_file_or_404(cursor, file_id)

    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        return get_file_or_404(cursor, file_id)

    set_clause = ", ".join(f"`{c}` = %s" for c in fields)
    execute(
        cursor,
        f"UPDATE `intake_files` SET {set_clause}, `updated_at` = {NOW_SQL} "
        "WHERE `id` = %s",
        tuple(fields.values()) + (file_id,),
    )
    log.info("intake_file_updated", file_id=file_id, fields=sorted(fields))
    return get_file_or_404(cursor, file_id)


def counts(cursor, batch_id: Optional[str] = None) -> IntakeCounts:
    by_status = status_counts(cursor, batch_id)
    tally = IntakeCounts(total=sum(by_status.values()))
    for status, n in by_status.items():
        if status in STATUSES:
            setattr(tally, status, n)
    return tally


BULK_ROWS = 500


def _chunks(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _placeholders(n: int) -> str:
    return ", ".join(["%s"] * n)


def create_files(cursor, rows: List[dict]) -> int:
    written = 0
    per_row = f"({_placeholders(len(_INSERT_COLUMNS))}, {NOW_SQL}, {NOW_SQL})"
    for chunk in _chunks(rows, BULK_ROWS):
        params: list = []
        for row in chunk:
            values = {
                "id": row.get("id") or str(uuid.uuid4()),
                "output_path": None,
                "output_name": None,
                "claimed_by_file_id": None,
                "checksum": None,
                "patient_code": None,
                "path_code": None,
                "name_code": None,
                "reason": None,
                "detail": None,
                **row,
            }
            params.extend(values[c] for c in _INSERT_COLUMNS)
        execute(
            cursor,
            f"INSERT INTO `intake_files` ({_COLS}) VALUES "
            + ", ".join([per_row] * len(chunk)),
            tuple(params),
        )
        written += len(chunk)
    return written


def list_queued(cursor, prefixes: List[str], limit: int) -> List[IntakeFile]:
    if not prefixes:
        return []
    execute(
        cursor,
        f"SELECT {_COLS} FROM `intake_files` WHERE `status` = %s AND "
        f"substr(`id`, 1, 2) IN ({_placeholders(len(prefixes))}) LIMIT {int(limit)}",
        ("queued", *prefixes),
    )
    return [_row_to_file(r) for r in cursor.fetchall()]


def set_status_many(cursor, ids: List[str], status: str) -> None:
    for chunk in _chunks(list(ids), BULK_ROWS):
        execute(
            cursor,
            f"UPDATE `intake_files` SET `status` = %s, `updated_at` = {NOW_SQL} "
            f"WHERE `id` IN ({_placeholders(len(chunk))})",
            (status, *chunk),
        )


def requeue_processing(cursor, prefixes: Optional[List[str]] = None) -> int:
    sql = f"SELECT `id` FROM `intake_files` WHERE `status` = %s"
    params: list = ["processing"]
    if prefixes is not None:
        if not prefixes:
            return 0
        sql += f" AND substr(`id`, 1, 2) IN ({_placeholders(len(prefixes))})"
        params.extend(prefixes)
    execute(cursor, sql, tuple(params))
    ids = [r[0] for r in cursor.fetchall()]
    if ids:
        set_status_many(cursor, ids, "queued")
    return len(ids)


RESULT_FIELDS = ("status", "output_path", "output_name", "detail")


def apply_results(cursor, results: List[dict]) -> None:
    for chunk in _chunks(list(results), BULK_ROWS // 2):
        sets = []
        params: list = []
        for field in RESULT_FIELDS:
            whens = " ".join(["WHEN %s THEN %s"] * len(chunk))
            sets.append(f"`{field}` = CASE `id` {whens} ELSE `{field}` END")
            for result in chunk:
                params.extend([result["id"], result.get(field)])
        ids = [r["id"] for r in chunk]
        execute(
            cursor,
            f"UPDATE `intake_files` SET {', '.join(sets)}, `updated_at` = {NOW_SQL} "
            f"WHERE `id` IN ({_placeholders(len(ids))})",
            tuple(params + ids),
        )


def status_counts(cursor, batch_id: Optional[str] = None) -> dict:
    sql = "SELECT `status`, count(*) FROM `intake_files`"
    params: tuple = ()
    if batch_id:
        sql += " WHERE `batch_id` = %s"
        params = (batch_id,)
    execute(cursor, sql + " GROUP BY `status`", params)
    return {status: int(n) for status, n in cursor.fetchall()}


def batch_counts(cursor) -> dict:
    execute(
        cursor,
        "SELECT `batch_id`, `status`, count(*) FROM `intake_files` "
        "GROUP BY `batch_id`, `status`",
    )
    out: dict = {}
    for batch_id, status, n in cursor.fetchall():
        out.setdefault(batch_id, {})[status] = int(n)
    return out


def find_by_paths(cursor, paths: List[str]) -> dict:
    out: dict = {}
    for chunk in _chunks(list(dict.fromkeys(paths)), BULK_ROWS):
        execute(
            cursor,
            f"SELECT {_COLS} FROM `intake_files` WHERE `source_path` IN ({_placeholders(len(chunk))})",
            tuple(chunk),
        )
        for row in cursor.fetchall():
            record = _row_to_file(row)
            out.setdefault(record.source_path, []).append(record)
    return out


def find_by_checksums(cursor, digests: List[str]) -> dict:
    out: dict = {}
    for chunk in _chunks(list(dict.fromkeys(d for d in digests if d)), BULK_ROWS):
        execute(
            cursor,
            f"SELECT {_COLS} FROM `intake_files` WHERE `checksum` IN ({_placeholders(len(chunk))})",
            tuple(chunk),
        )
        for row in cursor.fetchall():
            record = _row_to_file(row)
            out.setdefault(record.checksum, []).append(record)
    return out
