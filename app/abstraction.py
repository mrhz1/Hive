import csv
import json
import os
import re
import shutil
import stat
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app import document_info
from app.crud import abstraction_folders as crud
from app.crud import file_metadata as metadata_crud
from app.crud import patient_application_files as files_crud
from app.crud import patient_applications as applications_crud
from app.errors import ValidationError
from app.logging_setup import get_logger
from app.purge import is_deleted_file
from app.safe_cells import row as safe_row
from app.schemas import (
    AbstractionCriteria,
    AbstractionDocument,
    AbstractionFolder,
    AbstractionFolderCreate,
    User,
)
from app.storage import abstraction_root, resolve_stored_path, safe_path_segment

log = get_logger(__name__)

ACTIVE = "active"
DELETED = "deleted"
EXPIRED = "expired"

RELEASED_STATUSES = ("submitted",)
MANIFEST = "MANIFEST.csv"
MANIFEST_COLUMNS = ("file", "patient_id", "modality", "document_date", "file_type", "file_id")


def expiry_days() -> int:
    try:
        return max(1, int(os.environ.get("ABSTRACTION_EXPIRY_DAYS", "90")))
    except ValueError:
        return 90


def max_files() -> int:
    try:
        return max(1, int(os.environ.get("ABSTRACTION_MAX_FILES", "5000")))
    except ValueError:
        return 5000


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def new_expiry(days: Optional[int] = None) -> str:
    return _iso(_now() + timedelta(days=days or expiry_days()))


def is_due(folder: AbstractionFolder, now: Optional[datetime] = None) -> bool:
    if folder.status != ACTIVE or not folder.expires_at:
        return False
    try:
        expires = datetime.fromisoformat(folder.expires_at)
    except ValueError:
        return False
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires <= (now or _now())


def file_type_of(path_or_name: str) -> str:
    extension = Path(path_or_name).suffix.lower().lstrip(".")
    return "DICOM" if extension in ("dcm", "dicom") else (extension.upper() or "FILE")


def _available(cursor) -> List[Tuple[object, str]]:
    patients = {
        a.id: a.patient_id
        for a in applications_crud.list_applications(cursor)
        if a.status in RELEASED_STATUSES
    }
    out = []
    for record in files_crud.list_files(cursor):
        patient_id = patients.get(record.application_id)
        if not patient_id or is_deleted_file(record) or record.review_status == "rejected":
            continue
        if record.deid_status != "done" or not record.de_identified_file_path:
            continue
        out.append((record, patient_id))
    return out


def _document(record, patient_id: str) -> AbstractionDocument:
    name = record.deidentified_file_name or Path(record.de_identified_file_path).name
    parts = document_info.parse_name(name) or {}
    return AbstractionDocument(
        file_id=record.id,
        application_id=record.application_id,
        patient_id=patient_id,
        name=name,
        file_type=file_type_of(name),
        modality=parts.get("modality"),
        document_date=parts.get("day"),
    )


def _metadata_text(cursor) -> Dict[str, str]:
    return {
        row.file_id: json.dumps(row.metadata, default=str).lower()
        for row in metadata_crud.list_metadata(cursor)
    }


def _matches(doc: AbstractionDocument, criteria: AbstractionCriteria, text: str) -> bool:
    if criteria.patient_ids and doc.patient_id.upper() not in criteria.patient_ids:
        return False
    if criteria.modalities and (doc.modality or document_info.UNKNOWN) not in criteria.modalities:
        return False
    if criteria.file_types and doc.file_type not in criteria.file_types:
        return False
    if criteria.date_from or criteria.date_to:
        day = document_info.clean_date(doc.document_date or "")
        if not day or day == document_info.UNKNOWN:
            return False
        if criteria.date_from and day < criteria.date_from.strftime("%Y%m%d"):
            return False
        if criteria.date_to and day > criteria.date_to.strftime("%Y%m%d"):
            return False
    if criteria.search and criteria.search.strip().lower() not in text:
        return False
    return True


def matching(cursor, criteria: AbstractionCriteria) -> List[AbstractionDocument]:
    metadata = _metadata_text(cursor) if criteria.search else {}
    found = []
    for record, patient_id in _available(cursor):
        doc = _document(record, patient_id)
        text = f"{doc.name.lower()} {metadata.get(record.id, '')}"
        if _matches(doc, criteria, text):
            found.append(doc)
    return sorted(found, key=lambda d: (d.patient_id, d.document_date or "", d.name))


def _documents_by_id(cursor, file_ids: List[str]) -> Tuple[List[AbstractionDocument], int]:
    wanted = set(file_ids)
    found = [
        _document(record, patient_id)
        for record, patient_id in _available(cursor)
        if record.id in wanted
    ]
    return sorted(found, key=lambda d: (d.patient_id, d.document_date or "", d.name)), len(
        wanted - {d.file_id for d in found}
    )


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower()[:40] or "folder"


def folder_dir(owner: User, folder_id: str, name: str) -> Path:
    return abstraction_root() / safe_path_segment(owner.username) / f"{folder_id[:8]}-{_slug(name)}"


def _source_path(cursor, file_id: str) -> Path:
    return resolve_stored_path(files_crud.get_file_or_404(cursor, file_id).de_identified_file_path)


def _make_read_only(target: Path) -> None:
    for dirpath, dirnames, filenames in os.walk(target, topdown=False):
        for name in filenames:
            os.chmod(Path(dirpath) / name, stat.S_IRUSR | stat.S_IRGRP)
        os.chmod(dirpath, stat.S_IRUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP)


def remove_dir(target: Path) -> None:
    if not target.exists():
        return
    for dirpath, _dirnames, filenames in os.walk(target):
        os.chmod(dirpath, stat.S_IRWXU)
        for name in filenames:
            os.chmod(Path(dirpath) / name, stat.S_IRUSR | stat.S_IWUSR)
    shutil.rmtree(target)


def _copy(cursor, target: Path, docs: List[AbstractionDocument]) -> int:
    if target.exists():
        remove_dir(target)
    target.mkdir(parents=True)
    try:
        rows = []
        for doc in docs:
            source = _source_path(cursor, doc.file_id)
            if not source.is_file():
                raise ValidationError(f"'{doc.name}' is missing from disk")
            patient_dir = target / safe_path_segment(doc.patient_id)
            patient_dir.mkdir(exist_ok=True)
            shutil.copy2(source, patient_dir / doc.name)
            rows.append(
                [f"{patient_dir.name}/{doc.name}", doc.patient_id, doc.modality or "",
                 doc.document_date or "", doc.file_type, doc.file_id]
            )
        with open(target / MANIFEST, "w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(MANIFEST_COLUMNS)
            writer.writerows(safe_row(r) for r in rows)
        _make_read_only(target)
    except Exception:
        remove_dir(target)
        raise
    return len(docs)


def _checked(docs: List[AbstractionDocument]) -> None:
    if not docs:
        raise ValidationError("No de-identified documents of submitted applications match")
    if len(docs) > max_files():
        raise ValidationError(
            f"{len(docs)} documents match; a folder holds at most {max_files()}. "
            "Narrow the criteria."
        )


def create(cursor, payload: AbstractionFolderCreate, owner: User) -> AbstractionFolder:
    docs = matching(cursor, payload.criteria)
    _checked(docs)

    folder_id = str(uuid.uuid4())
    target = folder_dir(owner, folder_id, payload.name)
    count = _copy(cursor, target, docs)

    try:
        return crud.create_folder(
            cursor,
            {
                "id": folder_id,
                "name": payload.name,
                "purpose": payload.purpose,
                "owner_id": owner.id,
                "status": ACTIVE,
                "criteria": payload.criteria.model_dump_json(),
                "file_ids": json.dumps([d.file_id for d in docs]),
                "file_count": count,
                "folder_path": str(target),
                "expires_at": new_expiry(),
            },
        )
    except Exception:
        remove_dir(target)
        raise


def extend(cursor, folder: AbstractionFolder) -> AbstractionFolder:
    if folder.status != ACTIVE:
        raise ValidationError(f"The folder is {folder.status}; make it again instead")
    return crud.update_folder(cursor, folder.id, {"expires_at": new_expiry()})


def regenerate(cursor, folder: AbstractionFolder) -> Tuple[AbstractionFolder, int]:
    docs, missing = _documents_by_id(cursor, crud.file_ids(cursor, folder.id))
    _checked(docs)
    target = Path(folder.folder_path) if folder.folder_path else None
    if target is None:
        raise ValidationError("The folder has no path on record")
    count = _copy(cursor, target, docs)
    updated = crud.update_folder(
        cursor,
        folder.id,
        {
            "status": ACTIVE,
            "file_ids": json.dumps([d.file_id for d in docs]),
            "file_count": count,
            "expires_at": new_expiry(),
            "deleted_at": None,
            "deleted_by_id": None,
            "deleted_reason": None,
        },
    )
    return updated, missing


def delete(
    cursor,
    folder: AbstractionFolder,
    actor_id: Optional[str],
    reason: Optional[str],
    status: str = DELETED,
) -> AbstractionFolder:
    if folder.status != ACTIVE:
        raise ValidationError(f"The folder is already {folder.status}")
    if folder.folder_path:
        remove_dir(Path(folder.folder_path))
    return crud.update_folder(
        cursor,
        folder.id,
        {
            "status": status,
            "deleted_at": _iso(_now()),
            "deleted_by_id": actor_id,
            "deleted_reason": (reason or "").strip() or None,
        },
    )


def documents(cursor, folder: AbstractionFolder) -> List[AbstractionDocument]:
    docs, _missing = _documents_by_id(cursor, crud.file_ids(cursor, folder.id))
    return docs


def expire_due(cursor, now: Optional[datetime] = None) -> List[AbstractionFolder]:
    expired = []
    for folder in crud.list_folders(cursor):
        if not is_due(folder, now):
            continue
        try:
            expired.append(delete(cursor, folder, None, "expired", status=EXPIRED))
            log.info("abstraction_folder_expired", folder_id=folder.id)
        except Exception as e:
            log.error("abstraction_folder_expiry_failed", folder_id=folder.id, error=str(e))
    return expired
