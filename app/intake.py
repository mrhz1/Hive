import hashlib
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from app import storage
from app.crud import intake_files as crud
from app.crud import patient_application_files as files_crud
from app.crud import patients as patients_crud
from app.deid import DEIDENTIFIABLE_LABEL, is_deidentifiable
from app.filetype import read_header, resolve_extension
from app.ids import clean_patient_code, is_patient_code
from app.logging_setup import get_logger
from app.schemas import IntakeFileUpdate, PatientApplicationFileUpdate
from app.uploads import record_metadata

log = get_logger(__name__)

BATCH_MARKER = os.environ.get("INTAKE_BATCH_MARKER", "batch.done")
DEFAULT_SETTLE_SECONDS = 20.0
SKIP_DIRS = ["_reports", ".intake"]
WALK_SLACK_SECONDS = 2.0
MAX_SAMPLES = 2000
GROUP_SIZE = 500

QUEUED = "queued"
SKIPPED = "skipped"
CONFLICT = "conflict"
SUPERSEDED = "superseded"

UNSUPPORTED_FORMAT = "unsupported format"
NO_PATIENT_CODE = "no patient code"
CODE_CONFLICT = "path and file name disagree"

CODE_AT_START = re.compile(r"^([A-Za-z0-9]+)")


def intake_root():
    return storage.intake_root()


def deidentified_dir_name():
    return os.environ.get("INTAKE_DEID_DIRNAME", "de_identified")


def deidentified_root(root=None):
    return (root or intake_root()) / deidentified_dir_name()


def settle_seconds():
    value = os.environ.get("INTAKE_SETTLE_SECONDS")
    if not value:
        return DEFAULT_SETTLE_SECONDS
    try:
        return float(value)
    except ValueError:
        return DEFAULT_SETTLE_SECONDS


@dataclass
class Detection:
    path_code: Optional[str] = None
    name_code: Optional[str] = None

    @property
    def conflicted(self):
        return bool(self.path_code and self.name_code and self.path_code != self.name_code)

    @property
    def code(self):
        if self.conflicted:
            return None
        return self.path_code or self.name_code


@dataclass
class Candidate:
    path: Path
    relative_path: str
    extension: str
    size: int
    status: str
    detection: Detection
    reason: Optional[str] = None
    detail: Optional[str] = None

    @property
    def code(self):
        return self.detection.code

    @property
    def name(self):
        return self.path.name


def code_in_name(name):
    stem = Path(name).stem
    if not stem:
        return None

    code = clean_patient_code(stem)
    if is_patient_code(code):
        return code

    match = CODE_AT_START.match(stem)
    if not match:
        return None
    code = clean_patient_code(match.group(1))
    if is_patient_code(code):
        return code
    return None


def code_in_path(relative_path):
    folders = Path(relative_path).parts[:-1]
    for folder in reversed(folders):
        code = clean_patient_code(folder)
        if is_patient_code(code):
            return code
    return None


def detect(relative_path):
    return Detection(
        path_code=code_in_path(relative_path),
        name_code=code_in_name(Path(relative_path).name),
    )


def last_touched(stat):
    return max(stat.st_mtime, stat.st_ctime)


def is_settled(path, limit=None):
    if limit is None:
        limit = settle_seconds()
    try:
        stat = path.stat()
    except OSError:
        return False
    if limit <= 0:
        return True
    return time.time() - last_touched(stat) >= limit


def batch_is_marked_done(folder):
    return (folder / BATCH_MARKER).is_file()


def walk_folders(root=None, since=None):
    root = root or intake_root()
    if not root.is_dir():
        return

    submitted = storage.submitted_root().resolve()
    skip_at_top = [deidentified_dir_name()] + SKIP_DIRS

    for dirpath, dirnames, filenames in os.walk(root):
        folder = Path(dirpath)

        keep = []
        for name in sorted(dirnames):
            if name.startswith("."):
                continue
            if folder == root and name in skip_at_top:
                continue
            try:
                if (folder / name).resolve().is_relative_to(submitted):
                    continue
            except OSError:
                continue
            keep.append(name)
        dirnames[:] = keep

        try:
            folder_time = last_touched(folder.stat())
        except OSError:
            continue
        if since is not None and folder_time <= since - WALK_SLACK_SECONDS:
            continue

        yield folder, folder_time, sorted(filenames)


def walk(root=None, since=None):
    for folder, _, names in walk_folders(root, since):
        for name in names:
            if name == BATCH_MARKER or name.startswith("."):
                continue
            path = folder / name
            if path.is_file():
                yield path


def checksum(path, chunk_size=1024 * 1024):
    sha = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                sha.update(chunk)
    except OSError as e:
        log.warning("intake_checksum_failed", path=str(path), error=str(e))
        return ""
    return sha.hexdigest()


def classify(path, root=None):
    root = root or intake_root()
    relative = str(path.relative_to(root))
    extension = resolve_extension(path.name, read_header(path))
    try:
        size = path.stat().st_size
    except OSError:
        size = 0

    detection = detect(relative)
    candidate = Candidate(
        path=path,
        relative_path=relative,
        extension=extension,
        size=size,
        status=QUEUED,
        detection=detection,
    )

    if not is_deidentifiable(extension):
        candidate.status = SKIPPED
        candidate.reason = UNSUPPORTED_FORMAT
        candidate.detail = f"'{extension or 'no extension'}' (handled: {DEIDENTIFIABLE_LABEL})"
    elif detection.conflicted:
        candidate.status = CONFLICT
        candidate.reason = CODE_CONFLICT
        candidate.detail = (
            f"the path says {detection.path_code}, the file name says {detection.name_code}"
        )
    elif not detection.code:
        candidate.status = SKIPPED
        candidate.reason = NO_PATIENT_CODE
        candidate.detail = "no code in the path or the file name"

    return candidate


def survey(root=None):
    root = root or intake_root()
    return [classify(path, root) for path in walk(root)]


def mirrored_dir(relative_path, root=None):
    return deidentified_root(root) / Path(relative_path).parent


@dataclass
class SweepResult:
    batch_id: Optional[str] = None
    candidates: List[Candidate] = field(default_factory=list)
    recorded: int = 0
    already_seen: int = 0
    superseded: int = 0
    retried: int = 0
    counts: dict = field(default_factory=dict)

    def add(self, candidate):
        self.counts[candidate.status] = self.counts.get(candidate.status, 0) + 1
        if len(self.candidates) < MAX_SAMPLES:
            self.candidates.append(candidate)

    def count(self, status):
        if self.counts:
            return self.counts.get(status, 0)
        return len(self.with_status(status))

    def with_status(self, status):
        return [c for c in self.candidates if c.status == status]

    @property
    def total(self):
        if self.counts:
            return sum(self.counts.values())
        return len(self.candidates)

    @property
    def queued(self):
        return self.with_status(QUEUED)

    @property
    def skipped(self):
        return self.with_status(SKIPPED)

    @property
    def conflicts(self):
        return self.with_status(CONFLICT)


def sweep(cursor, root=None, dry_run=True, touched_since=None, full=True):
    root = root or intake_root()
    result = SweepResult()
    since = None if full else touched_since

    batch = None
    group = []
    for path in walk(root, since=since):
        candidate = classify(path, root)
        result.add(candidate)
        if dry_run:
            continue
        group.append(candidate)
        if len(group) >= GROUP_SIZE:
            batch = save_group(cursor, root, group, touched_since, result, batch)
            group = []
    if group and not dry_run:
        batch = save_group(cursor, root, group, touched_since, result, batch)

    if dry_run:
        log.info(
            "intake_sweep_dry_run",
            root=str(root),
            found=result.total,
            queued=result.count(QUEUED),
            skipped=result.count(SKIPPED),
            conflicts=result.count(CONFLICT),
        )
        return result

    if batch is not None:
        crud.finish_batch(cursor, batch.id, "swept")

    log.info(
        "intake_sweep_recorded",
        batch_id=result.batch_id,
        root=str(root),
        full=full,
        recorded=result.recorded,
        already_seen=result.already_seen,
        superseded=result.superseded,
        retried=result.retried,
        walked_redactable=result.count(QUEUED),
        walked_skipped=result.count(SKIPPED),
        walked_conflicts=result.count(CONFLICT),
    )
    return result


def changed_since(path, since):
    if since is None:
        return False
    try:
        return last_touched(path.stat()) > since
    except OSError:
        return False


def status_update(row_id, status, detail):
    return {
        "id": row_id,
        "status": status,
        "output_path": None,
        "output_name": None,
        "detail": detail,
    }


def save_group(cursor, root, group, touched_since, result, batch):
    rows_by_path = crud.find_by_paths(cursor, [str(c.path) for c in group])

    new_files = []
    for candidate in group:
        rows = rows_by_path.get(str(candidate.path), [])
        same_size = any(r.file_size == candidate.size for r in rows)
        if rows and same_size and not changed_since(candidate.path, touched_since):
            result.already_seen += 1
        else:
            new_files.append(candidate)
    if not new_files:
        return batch

    checksums = {}
    for candidate in new_files:
        checksums[str(candidate.path)] = checksum(candidate.path)
    rows_by_checksum = crud.find_by_checksums(cursor, [c for c in checksums.values() if c])

    new_rows = []
    updates = []
    for candidate in new_files:
        path = str(candidate.path)
        digest = checksums[path]
        same_bytes = rows_by_checksum.get(digest, []) if digest else []

        same_file = [r for r in same_bytes if r.source_path == path]
        if same_file:
            failed = [r for r in same_file if r.status == "failed"]
            if failed and changed_since(candidate.path, touched_since):
                for row in failed:
                    updates.append(status_update(row.id, QUEUED, "retried: the file was pushed again"))
                    result.retried += 1
            else:
                result.already_seen += 1
            continue

        old_rows = [r for r in same_bytes if r.status in (SKIPPED, CONFLICT)]
        for r in rows_by_path.get(path, []):
            if r.status in (SKIPPED, CONFLICT, "failed") and r not in old_rows:
                old_rows.append(r)

        row_id = str(uuid.uuid4())
        new_rows.append(
            {
                "id": row_id,
                "source_path": path,
                "relative_path": candidate.relative_path,
                "file_name": candidate.name,
                "file_extension": candidate.extension,
                "file_size": candidate.size,
                "status": candidate.status,
                "checksum": digest,
                "patient_code": candidate.code,
                "path_code": candidate.detection.path_code,
                "name_code": candidate.detection.name_code,
                "reason": candidate.reason,
                "detail": candidate.detail,
            }
        )
        result.recorded += 1

        if candidate.status == QUEUED:
            for old in old_rows:
                detail = (
                    f"the same document was accepted as {candidate.relative_path} ({candidate.code})"
                )
                updates.append(status_update(old.id, SUPERSEDED, detail))
                result.superseded += 1

        if digest:
            rows_by_checksum.setdefault(digest, []).append(
                SeenRow(id=row_id, source_path=path, status=candidate.status)
            )

    if new_rows:
        if batch is None:
            batch = crud.create_batch(cursor, str(root))
            result.batch_id = batch.id
        for row in new_rows:
            row["batch_id"] = batch.id
        crud.create_files(cursor, new_rows)
    if updates:
        crud.apply_results(cursor, updates)
    return batch


@dataclass
class SeenRow:
    id: str
    source_path: str
    status: str


def retry(cursor, file_id):
    record = crud.get_file_or_404(cursor, file_id)
    if record.status != "failed":
        raise ValueError(f"'{record.file_name}' has not failed (it is {record.status})")
    if not Path(record.source_path).is_file():
        raise ValueError(
            f"'{record.file_name}' is no longer at {record.source_path}; push it again instead"
        )
    return crud.update_file(cursor, file_id, IntakeFileUpdate(status=QUEUED, detail="retried by hand"))


def resolve_conflict(cursor, file_id, code):
    record = crud.get_file_or_404(cursor, file_id)
    code = clean_patient_code(code)

    if record.status != CONFLICT:
        raise ValueError(f"'{record.file_name}' is not in conflict")

    options = sorted({c for c in [record.path_code, record.name_code] if c})
    if code not in options:
        raise ValueError(
            f"{code} is not one of the codes on this file ({', '.join(options) or 'none'})"
        )

    return crud.update_file(
        cursor,
        file_id,
        IntakeFileUpdate(
            patient_code=code,
            status=QUEUED,
            reason=None,
            detail=f"conflict resolved to {code}",
        ),
    )


def common_folder(paths):
    if not paths:
        return ""
    folders = [str(Path(p).parent) for p in paths]
    try:
        return os.path.commonpath(folders)
    except ValueError:
        return folders[0]


def available_codes(cursor):
    paths_by_code = {}
    for record in crud.list_files(cursor, status="done"):
        if record.patient_code:
            paths_by_code.setdefault(record.patient_code, []).append(record.source_path)

    codes = []
    for code in sorted(paths_by_code):
        paths = paths_by_code[code]
        codes.append(
            {
                "code": code,
                "files": len(paths),
                "folder": common_folder(paths),
                "patient_exists": patients_crud.get_patient(cursor, code) is not None,
            }
        )
    return codes


class AttachError(ValueError):
    pass


def attach_to_application(cursor, application, intake_file_ids):
    code = application.patient_id
    if not intake_file_ids:
        raise AttachError("Choose at least one file to attach")

    records = []
    for file_id in dict.fromkeys(intake_file_ids):
        record = crud.get_file(cursor, file_id)
        if record is None:
            raise AttachError(f"Intake file '{file_id}' not found")
        if record.status == "claimed":
            raise AttachError(f"'{record.file_name}' is already attached to another application")
        if record.status != "done":
            raise AttachError(
                f"'{record.file_name}' has not been de-identified (it is {record.status})"
            )
        if record.patient_code != code:
            raise AttachError(f"'{record.file_name}' belongs to {record.patient_code}, not {code}")
        if not record.output_path or not Path(record.output_path).is_file():
            raise AttachError(f"The redacted copy of '{record.file_name}' is missing from disk")
        records.append(record)

    attached = []
    for record in records:
        new_file = files_crud.create_file(
            cursor,
            application_id=application.id,
            original_file_name=record.file_name,
            sanitized_file_name=record.output_name or record.file_name,
            file_extension=record.file_extension,
            mime_type=storage.guess_mime_type(record.file_name, None),
            file_size=record.file_size,
            file_path=record.source_path,
            description=f"from intake: {record.relative_path}",
        )
        new_file = files_crud.update_file(
            cursor,
            new_file.id,
            PatientApplicationFileUpdate(
                deid_status="done",
                is_deidentified=True,
                deidentified_file_name=record.output_name,
                de_identified_file_path=record.output_path,
            ),
        )
        record_metadata(cursor, new_file.id, Path(record.source_path), record.file_extension)
        crud.update_file(
            cursor, record.id, IntakeFileUpdate(status="claimed", claimed_by_file_id=new_file.id)
        )
        attached.append(new_file)

    log.info("intake_files_attached", application_id=application.id, code=code, attached=len(attached))
    return attached


def release_claim(cursor, application_file_id):
    released = False
    for record in crud.list_files(cursor, status="claimed"):
        if record.claimed_by_file_id == application_file_id:
            crud.update_file(cursor, record.id, IntakeFileUpdate(status="done", claimed_by_file_id=None))
            log.info("intake_claim_released", intake_file_id=record.id)
            released = True
    return released


def mark_submitted(cursor, application_file_id):
    for record in crud.list_files(cursor, status="claimed"):
        if record.claimed_by_file_id == application_file_id:
            crud.update_file(cursor, record.id, IntakeFileUpdate(status="submitted"))
