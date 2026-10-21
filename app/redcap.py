import os
import re
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel

from app.crud import patients as patients_crud
from app.db import execute
from app.errors import ValidationError
from app.logging_setup import get_logger
from app.patient_import import _key, _read_rows, _text

log = get_logger(__name__)

MAX_ROWS = 100000
BATCH = 200

DICTIONARY, RECORDS, LOG = "dictionary", "records", "log"
KINDS = (DICTIONARY, RECORDS, LOG)

DATASET_NAME = re.compile(r"^[a-z0-9][a-z0-9_]{0,39}$")

EVENT_COLUMNS = {"redcapeventname": "event", "redcaprepeatinstance": "instance"}
SKIPPED_COLUMNS = {"redcaprepeatinstrument", "redcapdataaccessgroup"}

DICTIONARY_COLUMNS = {
    "variablefieldname": "field_name",
    "fieldname": "field_name",
    "formname": "form_name",
    "fieldtype": "field_type",
    "fieldlabel": "label",
    "choicescalculationsorsliderlabels": "choices",
    "selectchoicesorcalculations": "choices",
    "textvalidationtypeorshowslidernumber": "validation",
    "identifier": "identifier",
}

LOG_COLUMNS = {
    "timedate": "logged_at",
    "timestamp": "logged_at",
    "username": "username",
    "action": "action",
    "listofdatachangesorfieldsexported": "details",
    "details": "details",
    "record": "record",
}

CHOICE_TYPES = {"radio", "dropdown", "checkbox", "yesno", "truefalse", "slider", "calc"}

FIELD_COLUMNS = (
    "id", "dataset", "field_name", "form_name", "field_type", "validation",
    "label", "choices", "identifier", "imported_by_id", "imported_at",
)
VALUE_COLUMNS = (
    "id", "dataset", "patient_id", "event", "instance", "field_name", "value",
    "imported_by_id", "imported_at",
)
LOG_TABLE_COLUMNS = (
    "id", "dataset", "logged_at", "username", "action", "record", "details",
    "imported_by_id", "imported_at",
)

RECORD_IN_ACTION = re.compile(r"record\s+(\S+)", re.I)


class Field(BaseModel):
    dataset: str
    field_name: str
    form_name: Optional[str] = None
    field_type: str = "text"
    validation: Optional[str] = None
    label: Optional[str] = None
    choices: Optional[str] = None
    identifier: bool = False


class ImportResult(BaseModel):
    dataset: str
    kind: str
    applied: bool
    counts: Dict[str, int]
    problems: List[str] = []
    notes: List[str] = []


class DatasetSummary(BaseModel):
    dataset: str
    fields: int
    patients: int
    values: int
    log_entries: int
    last_import: Optional[str] = None


def mode() -> str:
    return "api" if os.environ.get("REDCAP_URL") else "files"


def check_dataset(name: str) -> str:
    cleaned = (name or "").strip().lower()
    if not DATASET_NAME.match(cleaned):
        raise ValidationError(
            "Dataset name: lowercase letters, digits and _, up to 40 characters (e.g. avsd_clinical)"
        )
    return cleaned


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _cols(columns) -> str:
    return ", ".join(f"`{c}`" for c in columns)


def _insert(cursor, table: str, columns, rows: List[dict]) -> None:
    placeholders = "(" + ", ".join(["%s"] * len(columns)) + ")"
    for start in range(0, len(rows), BATCH):
        part = rows[start : start + BATCH]
        execute(
            cursor,
            f"INSERT INTO `{table}` ({_cols(columns)}) VALUES " + ", ".join([placeholders] * len(part)),
            tuple(row.get(c) for row in part for c in columns),
        )


def _delete_ids(cursor, table: str, ids: List[str]) -> None:
    for start in range(0, len(ids), BATCH):
        part = ids[start : start + BATCH]
        execute(
            cursor,
            f"DELETE FROM `{table}` WHERE `id` IN ({', '.join(['%s'] * len(part))})",
            tuple(part),
        )


def _select(cursor, table: str, columns, dataset: Optional[str] = None) -> List[dict]:
    sql = f"SELECT {_cols(columns)} FROM `{table}`"
    params: tuple = ()
    if dataset:
        sql += " WHERE `dataset` = %s"
        params = (dataset,)
    execute(cursor, sql, params)
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _table(name: str, data: bytes) -> Tuple[List[str], List[List[object]]]:
    rows = _read_rows(name, data, MAX_ROWS)
    while rows and not any(_text(v) for v in rows[0]):
        rows.pop(0)
    if not rows:
        raise ValidationError("The file is empty")
    if len(rows) - 1 > MAX_ROWS:
        raise ValidationError(f"The file has more than {MAX_ROWS} rows; split it")
    header = [_text(h) or "" for h in rows[0]]
    body = [r for r in rows[1:] if any(_text(v) for v in r)]
    return header, body


def _yes(value) -> bool:
    return (_text(value) or "").lower() in ("y", "yes", "1", "true")


def fields(cursor, dataset: Optional[str] = None) -> List[Field]:
    found = _select(cursor, "redcap_fields", FIELD_COLUMNS, dataset)
    order = {row["id"]: index for index, row in enumerate(found)}
    found.sort(key=lambda r: (r["dataset"], r.get("imported_at") or "", order[r["id"]]))
    return [
        Field(**{k: v for k, v in row.items() if k in Field.model_fields and v is not None})
        for row in found
    ]


def import_dictionary(cursor, dataset: str, name: str, data: bytes, apply: bool, actor_id: Optional[str]) -> ImportResult:
    dataset = check_dataset(dataset)
    header, body = _table(name, data)
    columns = [DICTIONARY_COLUMNS.get(_key(h)) for h in header]
    if "field_name" not in columns or "field_type" not in columns:
        raise ValidationError(
            "This is not a REDCap data dictionary: it needs 'Variable / Field Name' and 'Field Type' columns"
        )
    problems, parsed, seen = [], [], set()
    for line, raw in enumerate(body, start=2):
        values = {c: v for c, v in zip(columns, raw) if c}
        name_ = (_text(values.get("field_name")) or "").lower()
        if not name_:
            problems.append(f"Line {line}: no field name")
            continue
        if name_ in seen:
            problems.append(f"Line {line}: '{name_}' appears twice")
            continue
        seen.add(name_)
        parsed.append(
            {
                "dataset": dataset,
                "field_name": name_,
                "form_name": _text(values.get("form_name")),
                "field_type": (_text(values.get("field_type")) or "text").lower(),
                "validation": (_text(values.get("validation")) or "").lower() or None,
                "label": _text(values.get("label")),
                "choices": _text(values.get("choices")),
                "identifier": _yes(values.get("identifier")),
            }
        )
    released = sum(1 for f in parsed if release_kind(Field(**f)))
    counts = {
        "fields": len(parsed),
        "forms": len({f["form_name"] for f in parsed if f["form_name"]}),
        "identifiers": sum(1 for f in parsed if f["identifier"]),
        "allowed_in_zone2": released,
    }
    notes = [
        f"{released} of {len(parsed)} fields can go to Zone 2; identifier and free-text fields never do"
    ]
    if apply and parsed:
        old = [row["id"] for row in _select(cursor, "redcap_fields", ("id",), dataset)]
        _delete_ids(cursor, "redcap_fields", old)
        now = _now()
        _insert(
            cursor,
            "redcap_fields",
            FIELD_COLUMNS,
            [{**f, "id": str(uuid.uuid4()), "imported_by_id": actor_id, "imported_at": now} for f in parsed],
        )
        log.info("redcap_dictionary_imported", dataset=dataset, fields=len(parsed))
    return ImportResult(dataset=dataset, kind=DICTIONARY, applied=apply and bool(parsed),
                        counts=counts, problems=problems, notes=notes)


def import_records(cursor, dataset: str, name: str, data: bytes, apply: bool, actor_id: Optional[str]) -> ImportResult:
    dataset = check_dataset(dataset)
    header, body = _table(name, data)
    if not header or not header[0]:
        raise ValidationError("The first column must be the REDCap record ID (the patient code)")
    record_column = header[0]
    special = {}
    data_columns = []
    for index, column in enumerate(header):
        if index == 0:
            continue
        key = _key(column)
        if key in EVENT_COLUMNS:
            special[EVENT_COLUMNS[key]] = index
        elif key in SKIPPED_COLUMNS or not column:
            continue
        else:
            data_columns.append((index, column.strip().lower()))

    codes = sorted({(_text(r[0]) or "").upper() for r in body if _text(r[0])})
    known = patients_crud.existing_ids(cursor, codes) if codes else set()
    unknown = [c for c in codes if c not in known]
    dictionary = {f.field_name for f in fields(cursor, dataset)}
    unlisted = sorted(
        {c for _, c in data_columns if dictionary and c.split("___")[0] not in dictionary}
    )

    rows, problems = [], []
    for line, raw in enumerate(body, start=2):
        code = (_text(raw[0]) or "").upper()
        if not code:
            problems.append(f"Line {line}: no record ID")
            continue
        if code not in known:
            continue
        event = _text(raw[special["event"]]) if "event" in special and special["event"] < len(raw) else None
        instance = _text(raw[special["instance"]]) if "instance" in special and special["instance"] < len(raw) else None
        for index, column in data_columns:
            value = _text(raw[index]) if index < len(raw) else None
            if value is None:
                continue
            rows.append(
                {"dataset": dataset, "patient_id": code, "event": event,
                 "instance": instance, "field_name": column, "value": value}
            )
    if unknown:
        problems.append(
            f"{len(unknown)} record IDs are not patients in the app and were skipped: "
            + ", ".join(unknown[:20]) + (" ..." if len(unknown) > 20 else "")
        )
    notes = [f"Record ID column: '{record_column}'"]
    if not dictionary:
        notes.append("No data dictionary for this dataset yet: import it so fields can go to Zone 2")
    elif unlisted:
        notes.append(
            f"{len(unlisted)} columns are not in the data dictionary and won't go to Zone 2: "
            + ", ".join(unlisted[:15]) + (" ..." if len(unlisted) > 15 else "")
        )
    patients = sorted({r["patient_id"] for r in rows})
    counts = {"patients": len(patients), "values": len(rows), "fields": len(data_columns),
              "unknown_records": len(unknown)}
    if apply and rows:
        existing = _select(cursor, "redcap_values", ("id", "patient_id"), dataset)
        replaced = set(patients)
        _delete_ids(cursor, "redcap_values", [r["id"] for r in existing if r["patient_id"] in replaced])
        now = _now()
        _insert(
            cursor,
            "redcap_values",
            VALUE_COLUMNS,
            [{**r, "id": str(uuid.uuid4()), "imported_by_id": actor_id, "imported_at": now} for r in rows],
        )
        notes.append("Each patient's earlier values in this dataset were replaced by this import")
        log.info("redcap_records_imported", dataset=dataset, patients=len(patients), values=len(rows))
    return ImportResult(dataset=dataset, kind=RECORDS, applied=apply and bool(rows),
                        counts=counts, problems=problems, notes=notes)


def import_log(cursor, dataset: str, name: str, data: bytes, apply: bool, actor_id: Optional[str]) -> ImportResult:
    dataset = check_dataset(dataset)
    header, body = _table(name, data)
    columns = [LOG_COLUMNS.get(_key(h)) for h in header]
    if "logged_at" not in columns or "action" not in columns:
        raise ValidationError("This is not a REDCap log: it needs 'Time / Date' and 'Action' columns")
    have = {
        (r["logged_at"], r["username"], r["action"], r["details"])
        for r in _select(cursor, "redcap_log", LOG_TABLE_COLUMNS, dataset)
    }
    new, repeated = [], 0
    for raw in body:
        values = {c: _text(v) for c, v in zip(columns, raw) if c}
        if not values.get("logged_at"):
            continue
        record = values.get("record")
        if not record:
            found = RECORD_IN_ACTION.search(values.get("action") or "")
            record = found.group(1) if found else None
        entry = {
            "dataset": dataset,
            "logged_at": values.get("logged_at"),
            "username": values.get("username"),
            "action": values.get("action"),
            "record": record,
            "details": values.get("details"),
        }
        key = (entry["logged_at"], entry["username"], entry["action"], entry["details"])
        if key in have:
            repeated += 1
            continue
        have.add(key)
        new.append(entry)
    counts = {"new_entries": len(new), "already_imported": repeated}
    if apply and new:
        now = _now()
        _insert(
            cursor,
            "redcap_log",
            LOG_TABLE_COLUMNS,
            [{**e, "id": str(uuid.uuid4()), "imported_by_id": actor_id, "imported_at": now} for e in new],
        )
        log.info("redcap_log_imported", dataset=dataset, entries=len(new))
    return ImportResult(dataset=dataset, kind=LOG, applied=apply and bool(new), counts=counts)


IMPORTERS = {DICTIONARY: import_dictionary, RECORDS: import_records, LOG: import_log}


def run_import(cursor, kind: str, dataset: str, name: str, data: bytes, apply: bool, actor_id: Optional[str]) -> ImportResult:
    if kind not in IMPORTERS:
        raise ValidationError(f"Unknown import '{kind}' (known: {', '.join(KINDS)})")
    return IMPORTERS[kind](cursor, dataset, name, data, apply, actor_id)


def summaries(cursor) -> List[DatasetSummary]:
    values = _select(cursor, "redcap_values", ("dataset", "patient_id", "imported_at"))
    field_rows = _select(cursor, "redcap_fields", ("dataset", "imported_at"))
    log_rows = _select(cursor, "redcap_log", ("dataset", "imported_at"))
    names = sorted({r["dataset"] for r in values + field_rows + log_rows})
    out = []
    for name in names:
        mine = [r for r in values if r["dataset"] == name]
        stamps = [r.get("imported_at") or "" for r in mine + field_rows + log_rows if r["dataset"] == name]
        out.append(
            DatasetSummary(
                dataset=name,
                fields=sum(1 for r in field_rows if r["dataset"] == name),
                patients=len({r["patient_id"] for r in mine}),
                values=len(mine),
                log_entries=sum(1 for r in log_rows if r["dataset"] == name),
                last_import=max(stamps) if stamps else None,
            )
        )
    return out


def release_kind(field: Field) -> Optional[str]:
    if field.identifier:
        return None
    kind = (field.field_type or "").lower()
    check = (field.validation or "").lower()
    if kind in CHOICE_TYPES:
        return "value"
    if kind == "text":
        if check.startswith("date"):
            return "date"
        if check in ("integer", "number") or check.startswith("number"):
            return "value"
    return None


def wide_rows(cursor, dataset: str, patient_ids: List[str]) -> Tuple[List[str], List[dict]]:
    wanted = set(patient_ids)
    values = [r for r in _select(cursor, "redcap_values", VALUE_COLUMNS, dataset) if r["patient_id"] in wanted]
    grouped: Dict[Tuple[str, str, str], dict] = {}
    seen_fields: List[str] = []
    for row in values:
        key = (row["patient_id"], row.get("event") or "", row.get("instance") or "")
        grouped.setdefault(key, {"patient_id": key[0], "event": key[1], "instance": key[2]})
        grouped[key][row["field_name"]] = row["value"]
        if row["field_name"] not in seen_fields:
            seen_fields.append(row["field_name"])
    order = [f.field_name for f in fields(cursor, dataset)]
    rank = {name: index for index, name in enumerate(order)}
    seen_fields.sort(key=lambda n: (rank.get(n.split("___")[0], len(rank)), n))
    return seen_fields, [grouped[k] for k in sorted(grouped)]


def datasets_with_values(cursor, patient_ids: List[str]) -> List[str]:
    wanted = set(patient_ids)
    return sorted(
        {r["dataset"] for r in _select(cursor, "redcap_values", ("dataset", "patient_id")) if r["patient_id"] in wanted}
    )


def patients_without_records(cursor, dataset: str) -> Tuple[str, List[str]]:
    dataset = check_dataset(dataset)
    have = {r["patient_id"] for r in _select(cursor, "redcap_values", ("patient_id",), dataset)}
    order = [f.field_name for f in fields(cursor, dataset)]
    record_field = order[0] if order else "record_id"
    codes = [p.id for p in patients_crud.list_patients(cursor) if p.id not in have]
    return record_field, sorted(codes)
