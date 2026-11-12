"""Explore a connected REDCap project and import from it, with a preview first.

The preview returns a fingerprint of exactly what REDCap sent. The import fetches
again and refuses if the fingerprint differs, so users import what they previewed.
Tokens never leave the server.
"""

import csv
import hashlib
import io
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel

from app import redcap, redcap_api
from app.errors import ConflictError, ValidationError

SAMPLE_ROWS = 10
SAMPLE_COLUMNS = 12
SAMPLE_CHARS = 60

# REDCap's "De-identified" export right drops these (plus the identifier flag).
FREE_TEXT_TYPES = {"notes"}


class RemoteDataset(BaseModel):
    dataset: str
    connected: bool
    project_id: Optional[int] = None
    title: Optional[str] = None
    in_production: Optional[bool] = None
    error: Optional[str] = None


class RemoteField(BaseModel):
    name: str
    label: str
    type: str
    left_out: Optional[str] = None  # identifier / date / free_text when De-identified


class RemoteInstrument(BaseModel):
    name: str
    label: str
    fields: int
    identifiers: int
    dates: int
    free_text: int
    field_list: List[RemoteField] = []


class RemotePreview(redcap.ImportResult):
    fingerprint: str
    instruments: List[str] = []
    rows_in_export: int = 0
    sample_columns: List[str] = []
    sample_rows: List[List[str]] = []


class NewRecordsPreview(BaseModel):
    dataset: str
    record_field: str
    count: int
    codes: List[str]
    connected: bool
    write_enabled: bool


def _token(dataset: str) -> str:
    dataset = redcap.check_dataset(dataset)
    token = dict(redcap_api.datasets()).get(dataset)
    if not redcap_api.configured() or not token:
        raise ValidationError(
            f"Dataset '{dataset}' is not connected to REDCap: it needs REDCAP_URL, "
            f"REDCAP_DATASETS and REDCAP_TOKEN_{dataset.upper()} on the server"
        )
    return token


def _rows(data: bytes) -> List[Dict[str, str]]:
    return list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))


def _table(data: bytes) -> Tuple[List[str], List[List[str]]]:
    reader = csv.reader(io.StringIO(data.decode("utf-8-sig")))
    header = next(reader, [])
    return header, [row for row in reader if any(cell.strip() for cell in row)]


def _sample(header: List[str], body: List[List[str]]) -> Tuple[List[str], List[List[str]]]:
    columns = header[:SAMPLE_COLUMNS]
    rows = [
        [(row[i] if i < len(row) else "")[:SAMPLE_CHARS] for i in range(len(columns))]
        for row in body[:SAMPLE_ROWS]
    ]
    return columns, rows


def _fingerprint(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:20]


def _removed_when_deidentified(field: Dict[str, str]) -> Optional[str]:
    if (field.get("identifier") or "").strip().lower() == "y":
        return "identifier"
    kind = (field.get("field_type") or "").lower()
    check = (field.get("text_validation_type_or_show_slider_number") or "").lower()
    if kind == "text" and check.startswith("date"):
        return "date"
    if kind in FREE_TEXT_TYPES or (kind == "text" and not check):
        return "free_text"
    return None


def overview() -> List[RemoteDataset]:
    out = []
    for name, token in redcap_api.datasets():
        if not redcap_api.configured() or not token:
            out.append(RemoteDataset(dataset=name, connected=False,
                                     error=f"REDCAP_TOKEN_{name.upper()} is not set"))
            continue
        try:
            info = redcap_api.project_info(token)
            out.append(RemoteDataset(
                dataset=name, connected=True, project_id=info.get("project_id"),
                title=info.get("project_title"), in_production=bool(info.get("in_production")),
            ))
        except redcap_api.RedcapError as exc:
            out.append(RemoteDataset(dataset=name, connected=False, error=exc.message))
    return out


def instrument_list(dataset: str) -> List[RemoteInstrument]:
    token = _token(dataset)
    forms = redcap_api.instruments(token)
    fields = _rows(redcap_api.export_dictionary(token))
    out = []
    for form in forms:
        mine = [f for f in fields if f.get("form_name") == form["instrument_name"]
                and (f.get("field_type") or "") != "descriptive"]
        removed = [_removed_when_deidentified(f) for f in mine]
        out.append(RemoteInstrument(
            name=form["instrument_name"], label=form.get("instrument_label") or form["instrument_name"],
            fields=len(mine), identifiers=removed.count("identifier"),
            dates=removed.count("date"), free_text=removed.count("free_text"),
            field_list=[
                RemoteField(name=f["field_name"], label=(f.get("field_label") or "")[:120],
                            type=f.get("field_type") or "", left_out=why)
                for f, why in zip(mine, removed)
            ],
        ))
    return out


def _fetch(cursor, dataset: str, kind: str, chosen: List[str]) -> Tuple[bytes, List[str], List[str], bool]:
    """Returns (data, instruments used, notes, only_these_fields)."""
    token = _token(dataset)
    if kind == redcap.DICTIONARY:
        return redcap_api.export_dictionary(token), [], [], False
    if kind == redcap.LOG:
        since = redcap.last_log_time(cursor, dataset)
        notes = [f"Only REDCap log entries since {since} (the last import)"] if since else []
        return redcap_api.export_log(token, since=since), [], notes, False
    if kind != redcap.RECORDS:
        raise ValidationError(f"Unknown import '{kind}' (known: {', '.join(redcap.KINDS)})")

    names = [f["instrument_name"] for f in redcap_api.instruments(token)]
    chosen = [c for c in dict.fromkeys(chosen or []) if c]
    unknown = [c for c in chosen if c not in names]
    if unknown:
        raise ValidationError(f"Not instruments of this project: {', '.join(unknown)}")
    if not chosen:
        raise ValidationError("Choose at least one instrument")
    everything = set(chosen) == set(names)
    dictionary = _rows(redcap_api.export_dictionary(token))
    record_field = dictionary[0]["field_name"] if dictionary else None
    patient_field = redcap_api.patient_field(dataset)
    if everything:
        data = redcap_api.export_records(token)
    else:
        keep = [f for f in (record_field, patient_field) if f]
        data = redcap_api.export_records(token, fields=keep, forms=chosen)

    header, _ = _table(data)
    present = {h.strip().lower().split("___")[0] for h in header}
    if patient_field and patient_field not in present:
        raise ValidationError(
            f"The patient code field '{patient_field}' is not in what REDCap sent. With "
            "De-identified export rights REDCap leaves out identifier fields: ask for Full Data Set "
            f"rights, or remove REDCAP_PATIENT_FIELD_{dataset.upper()} to use the record ID."
        )
    expected = [f["field_name"] for f in dictionary
                if f.get("form_name") in set(chosen) and (f.get("field_type") or "") != "descriptive"]
    missing = [f for f in expected if f not in present]
    notes = []
    if missing:
        notes.append(
            f"REDCap left out {len(missing)} of {len(expected)} fields of these instruments "
            f"(e.g. {', '.join(missing[:8])}). Your export rights decide this: De-identified "
            "removes identifiers, dates and free text."
        )
    return data, chosen, notes, not everything


def preview_or_import(cursor, dataset: str, kind: str, instruments: List[str], apply: bool,
                      actor_id: Optional[str], fingerprint: Optional[str] = None) -> RemotePreview:
    dataset = redcap.check_dataset(dataset)
    data, used, notes, partial = _fetch(cursor, dataset, kind, instruments)
    mark = _fingerprint(data)
    if apply and fingerprint != mark:
        raise ConflictError(
            "What REDCap sends has changed since your preview. Preview again to see what will be imported."
        )
    result = redcap.run_import(
        cursor, kind, dataset, f"{kind}.csv", data, apply, actor_id,
        redcap_api.patient_field(dataset), partial,
    )
    header, body = _table(data)
    columns, rows = _sample(header, body)
    return RemotePreview(
        **result.model_dump(exclude={"notes"}), notes=notes + result.notes,
        fingerprint=mark, instruments=used, rows_in_export=len(body),
        sample_columns=columns, sample_rows=rows,
    )


def new_records_preview(cursor, dataset: str) -> NewRecordsPreview:
    dataset = redcap.check_dataset(dataset)
    record_field, codes = redcap.patients_without_records(cursor, dataset)
    connected = bool(redcap_api.configured() and dict(redcap_api.datasets()).get(dataset))
    return NewRecordsPreview(
        dataset=dataset, record_field=record_field, count=len(codes), codes=codes[:100],
        connected=connected, write_enabled=redcap_api.write_enabled(),
    )


def send_new_records(cursor, dataset: str, expected_count: int) -> int:
    dataset = redcap.check_dataset(dataset)
    if not redcap_api.write_enabled():
        raise ValidationError("Sending to REDCap is switched off on the server (REDCAP_ALLOW_WRITE)")
    token = _token(dataset)
    if not redcap.fields(cursor, dataset):
        raise ValidationError("Import this dataset's data dictionary first, so the app knows the record ID field")
    record_field, codes = redcap.patients_without_records(cursor, dataset)
    if len(codes) != expected_count:
        raise ConflictError("The list of new patient codes changed since your preview. Preview again.")
    if not codes:
        return 0
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([record_field])
    for code in codes:
        writer.writerow([code])
    return redcap_api.import_records(token, buffer.getvalue())
