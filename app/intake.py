import hashlib
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from app import storage
from app.crud import patient_application_files as files_crud
from app.crud import patients as patients_crud
from app.deid import DEIDENTIFIABLE_LABEL, is_deidentifiable
from app.filetype import read_header, resolve_extension
from app.ids import clean_patient_code, is_patient_code
from app.logging_setup import get_logger
from app.schemas import PatientApplicationFileUpdate

log = get_logger(__name__)

DEFAULT_SETTLE_SECONDS = 20.0

UNSUPPORTED_FORMAT = "unsupported format"
NO_PATIENT_CODE = "no patient code"
CODE_CONFLICT = "path and file name disagree"
DUPLICATE = "duplicate"
REDACTION_FAILED = "redaction failed"

REASON_SUFFIX = ".reason.json"
SIDECAR_SUFFIX = ".json"
PARTIAL_SUFFIX = ".partial"

CODE_AT_START = re.compile(r"^([A-Za-z0-9]+)")

_overrides_lock = threading.Lock()


def intake_root():
    return storage.intake_root()


def data_root():
    return storage.data_root()


def original_root():
    return data_root() / "original"


def deidentified_root():
    return data_root() / "de_identified"


def failed_root():
    return data_root() / "failed"


def attention_root():
    return data_root() / "needs_attention"


def state_dir():
    return data_root() / ".intake"


def settle_seconds():
    value = os.environ.get("INTAKE_SETTLE_SECONDS")
    if not value:
        return DEFAULT_SETTLE_SECONDS
    try:
        return float(value)
    except ValueError:
        return DEFAULT_SETTLE_SECONDS


def is_data_file(path):
    if not path:
        return False
    try:
        return Path(path).resolve().is_relative_to(data_root().resolve())
    except OSError:
        return False


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
    detection: Detection
    code: Optional[str] = None
    reason: Optional[str] = None
    detail: Optional[str] = None

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


def walk(root=None):
    root = root or intake_root()
    if not root.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            path = Path(dirpath) / name
            if path.is_file():
                yield path


def is_extra_file(name):
    return name.endswith(REASON_SUFFIX) or name.endswith(SIDECAR_SUFFIX) or name.endswith(PARTIAL_SUFFIX)


def count_files(root):
    count = 0
    if not root.is_dir():
        return 0
    for _, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if not name.startswith(".") and not is_extra_file(name):
                count += 1
    return count


def load_overrides():
    path = state_dir() / "code_overrides.json"
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def set_override(relative_path, code):
    with _overrides_lock:
        overrides = load_overrides()
        overrides[relative_path] = code
        write_json(state_dir() / "code_overrides.json", overrides)


def remove_override(relative_path):
    with _overrides_lock:
        overrides = load_overrides()
        if relative_path in overrides:
            del overrides[relative_path]
            write_json(state_dir() / "code_overrides.json", overrides)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, default=str))
    tmp.replace(path)


def read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}


def classify(path, root=None, overrides=None):
    root = root or intake_root()
    relative = path.relative_to(root).as_posix()
    extension = resolve_extension(path.name, read_header(path))
    try:
        size = path.stat().st_size
    except OSError:
        size = 0

    detection = detect(relative)
    candidate = Candidate(
        path=path, relative_path=relative, extension=extension, size=size, detection=detection
    )

    if not is_deidentifiable(extension):
        candidate.reason = UNSUPPORTED_FORMAT
        candidate.detail = f"'{extension or 'no extension'}' (handled: {DEIDENTIFIABLE_LABEL})"
    elif overrides and relative in overrides:
        candidate.code = overrides[relative]
    elif detection.conflicted:
        candidate.reason = CODE_CONFLICT
        candidate.detail = (
            f"the path says {detection.path_code}, the file name says {detection.name_code}"
        )
    elif not detection.code:
        candidate.reason = NO_PATIENT_CODE
        candidate.detail = "no code in the path or the file name"
    else:
        candidate.code = detection.code

    return candidate


def checksum(path, chunk_size=1024 * 1024):
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            sha.update(chunk)
    return sha.hexdigest()


def is_duplicate(candidate):
    existing = original_root() / candidate.relative_path
    try:
        if not existing.is_file() or existing.stat().st_size != candidate.size:
            return False
        return checksum(existing) == checksum(candidate.path)
    except OSError:
        return False


def move_file(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        for n in range(2, 10_000):
            other = target.with_name(f"{target.stem}_{n}{target.suffix}")
            if not other.exists():
                target = other
                break
    os.replace(source, target)
    return target


def set_aside(candidate, root, reason, detail=None):
    target = move_file(candidate.path, root / candidate.relative_path)
    write_json(
        Path(str(target) + REASON_SUFFIX),
        {
            "reason": reason,
            "detail": detail,
            "relative_path": candidate.relative_path,
            "path_code": candidate.detection.path_code,
            "name_code": candidate.detection.name_code,
            "extension": candidate.extension,
            "size": candidate.size,
            "moved_at": time.time(),
        },
    )
    log.info("intake_file_set_aside", path=candidate.relative_path, reason=reason)
    return target


def problem_root(kind):
    if kind == "failed":
        return failed_root()
    if kind == "attention":
        return attention_root()
    raise ValueError(f"Unknown list '{kind}'")


def list_problem_files(kind):
    root = problem_root(kind)
    files = []
    for path in walk(root):
        if is_extra_file(path.name):
            continue
        info = read_json(str(path) + REASON_SUFFIX)
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "file_name": path.name,
                "full_path": str(path),
                "reason": info.get("reason"),
                "detail": info.get("detail"),
                "path_code": info.get("path_code"),
                "name_code": info.get("name_code"),
                "file_extension": info.get("extension") or path.suffix.lstrip(".").lower(),
                "file_size": size,
                "moved_at": info.get("moved_at"),
            }
        )
    return files


def safe_child(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or path == root.resolve():
        raise ValueError("Invalid file path")
    return path


def send_back(kind, relative):
    root = problem_root(kind)
    path = safe_child(root, relative)
    if not path.is_file():
        raise ValueError(f"'{relative}' is not in the {kind} list")
    info = read_json(str(path) + REASON_SUFFIX)
    original_relative = info.get("relative_path") or relative
    target = move_file(path, intake_root() / original_relative)
    Path(str(path) + REASON_SUFFIX).unlink(missing_ok=True)
    log.info("intake_file_sent_back", path=original_relative, source=kind)
    return target.relative_to(intake_root()).as_posix()


def retry_failed(relative):
    return send_back("failed", relative)


def resolve_conflict(relative, code):
    root = attention_root()
    path = safe_child(root, relative)
    info = read_json(str(path) + REASON_SUFFIX)
    if info.get("reason") != CODE_CONFLICT:
        raise ValueError(f"'{relative}' is not in conflict")

    code = clean_patient_code(code)
    options = sorted({c for c in [info.get("path_code"), info.get("name_code")] if c})
    if code not in options:
        raise ValueError(f"{code} is not one of the codes on this file ({', '.join(options)})")

    new_relative = send_back("attention", relative)
    set_override(new_relative, code)
    return new_relative


def redacted_files(code):
    folder = deidentified_root() / code
    files = []
    for path in walk(folder):
        if is_extra_file(path.name):
            continue
        files.append(path)
    return files


def common_folder(paths):
    if not paths:
        return ""
    folders = [str(Path(p).parent) for p in paths]
    try:
        return os.path.commonpath(folders)
    except ValueError:
        return folders[0]


def available_codes(cursor):
    root = deidentified_root()
    if not root.is_dir():
        return []

    files_by_code = {}
    for folder in sorted(root.iterdir()):
        if folder.is_dir() and not folder.name.startswith("."):
            files = redacted_files(folder.name)
            if files:
                files_by_code[folder.name] = files

    all_paths = [str(p) for files in files_by_code.values() for p in files]
    attached = files_crud.find_deidentified_paths(cursor, all_paths)
    existing = patients_crud.existing_ids(cursor, list(files_by_code))

    codes = []
    for code, files in files_by_code.items():
        free = [p for p in files if str(p) not in attached]
        if not free:
            continue
        relative_dirs = [p.relative_to(root / code) for p in free]
        codes.append(
            {
                "code": code,
                "files": len(free),
                "folder": str(original_root() / common_folder(relative_dirs)),
                "patient_exists": code in existing,
            }
        )
    return codes


def files_for_code(cursor, code):
    code = clean_patient_code(code)
    root = deidentified_root()
    files = redacted_files(code)
    attached = files_crud.find_deidentified_paths(cursor, [str(p) for p in files])

    result = []
    for path in files:
        if str(path) in attached:
            continue
        info = read_json(str(path) + SIDECAR_SUFFIX)
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        result.append(
            {
                "id": path.relative_to(root).as_posix(),
                "patient_code": code,
                "output_name": path.name,
                "file_name": info.get("original_name") or path.name,
                "relative_path": info.get("relative_path") or path.relative_to(root / code).as_posix(),
                "file_extension": path.suffix.lstrip(".").lower(),
                "file_size": size,
                "method": info.get("method"),
            }
        )
    return result


class AttachError(ValueError):
    pass


def attach_to_application(cursor, application, file_ids):
    from app.storage import guess_mime_type
    from app.uploads import record_metadata

    code = application.patient_id
    if not file_ids:
        raise AttachError("Choose at least one file to attach")

    root = deidentified_root()
    chosen = []
    for file_id in dict.fromkeys(file_ids):
        try:
            path = safe_child(root, file_id)
        except ValueError:
            raise AttachError(f"'{file_id}' is not a de-identified file")
        if Path(file_id).parts[0] != code:
            raise AttachError(f"'{path.name}' belongs to {Path(file_id).parts[0]}, not {code}")
        if not path.is_file():
            raise AttachError(f"'{path.name}' is missing from disk")
        info = read_json(str(path) + SIDECAR_SUFFIX)
        original = info.get("original_path")
        if not original or not Path(original).is_file():
            raise AttachError(f"The original of '{path.name}' is missing from disk")
        chosen.append((path, info))

    attached_already = files_crud.find_deidentified_paths(cursor, [str(p) for p, _ in chosen])
    for path, _ in chosen:
        if str(path) in attached_already:
            raise AttachError(f"'{path.name}' is already attached to an application")

    attached = []
    for path, info in chosen:
        original = Path(info["original_path"])
        extension = path.suffix.lstrip(".").lower()
        new_file = files_crud.create_file(
            cursor,
            application_id=application.id,
            original_file_name=original.name,
            sanitized_file_name=path.name,
            file_extension=extension,
            mime_type=guess_mime_type(original.name, None),
            file_size=original.stat().st_size,
            file_path=str(original),
            description=f"from intake: {info.get('relative_path', original.name)}",
        )
        new_file = files_crud.update_file(
            cursor,
            new_file.id,
            PatientApplicationFileUpdate(
                deid_status="done",
                is_deidentified=True,
                deidentified_file_name=path.name,
                de_identified_file_path=str(path),
            ),
        )
        record_metadata(cursor, new_file.id, original, extension)
        attached.append(new_file)

    log.info("intake_files_attached", application_id=application.id, code=code, attached=len(attached))
    return attached


def list_reports(limit=20):
    folder = state_dir() / "reports"
    if not folder.is_dir():
        return []
    reports = []
    for path in sorted(folder.glob("*.json"), reverse=True)[:limit]:
        data = read_json(path)
        if data:
            reports.append(data)
    return reports
