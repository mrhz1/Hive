import ntpath
import os
import stat as stat_module
import threading
import time
from pathlib import Path, PurePosixPath
from typing import Dict, Iterator, List, Tuple

from app import intake, intake_progress
from app.errors import ConflictError, ValidationError
from app.logging_setup import get_logger

log = get_logger(__name__)

CHUNK = 4 * 1024 * 1024
MAX_ERRORS = 20


def server() -> str:
    return os.environ.get("CARBON_SERVER", "carbon.research.sickkids.ca")


def share() -> str:
    return os.environ.get("CARBON_SHARE", rf"\\{server()}\imagecorelab")


def _smb():
    try:
        import smbclient
    except ImportError as exc:
        raise ValidationError(
            "The Carbon connection needs the smbprotocol package (pip install smbprotocol[kerberos])"
        ) from exc
    return smbclient


_session_lock = threading.Lock()
_connected = {"server": None}


def connect():
    smb = _smb()
    with _session_lock:
        if _connected["server"] == server():
            return smb
        user = os.environ.get("CARBON_USER", "")
        password = os.environ.get("CARBON_PASSWORD", "")
        try:
            if user and password:
                smb.register_session(server(), username=user, password=password)
            else:
                smb.register_session(server(), auth_protocol="kerberos")
        except Exception as exc:
            raise ValidationError(f"Could not log in to {server()}: {exc}") from exc
        _connected["server"] = server()
    return smb


def reset_session():
    with _session_lock:
        _connected["server"] = None


def clean_relative(path: str) -> PurePosixPath:
    parts = [p for p in (path or "").replace("\\", "/").split("/") if p]
    for part in parts:
        if part in (".", ".."):
            raise ValidationError(f"Invalid folder '{path}'")
    return PurePosixPath(*parts) if parts else PurePosixPath()


def remote_path(relative: PurePosixPath) -> str:
    return ntpath.join(share(), *relative.parts) if relative.parts else share()


def list_folder(path: str) -> Dict:
    relative = clean_relative(path)
    smb = connect()
    try:
        found = list(smb.scandir(remote_path(relative)))
    except Exception as exc:
        raise ValidationError(f"Could not open '{relative or share()}': {exc}") from exc
    entries = []
    for entry in found:
        if entry.name.startswith("."):
            continue
        is_dir = entry.is_dir()
        try:
            size = 0 if is_dir else entry.stat().st_size
        except Exception:
            size = 0
        entries.append(
            {
                "name": entry.name,
                "path": str(relative / entry.name),
                "is_dir": is_dir,
                "size": size,
            }
        )
    entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
    return {"path": str(relative) if relative.parts else "", "share": share(), "entries": entries}


def already_here(relative: Path) -> bool:
    places = [
        intake.intake_root(),
        intake.original_root(),
        intake.submitted_data_root() / "original",
    ]
    return any((place / relative).exists() for place in places)


def _files_under(smb, relative: PurePosixPath) -> Iterator[Tuple[str, PurePosixPath, int]]:
    remote = remote_path(relative)
    info = smb.stat(remote)
    if not _is_dir(info):
        yield remote, relative, info.st_size
        return
    for dirpath, dirnames, filenames in smb.walk(remote):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            full = ntpath.join(dirpath, name)
            parts = ntpath.relpath(full, share()).split("\\")
            yield full, PurePosixPath(*parts), smb.stat(full).st_size


def _is_dir(info) -> bool:
    return stat_module.S_ISDIR(info.st_mode)


def plan(paths: List[str]) -> Dict:
    if not paths:
        raise ValidationError("Pick at least one folder or file")
    smb = connect()
    todo, skipped, size, seen = [], 0, 0, set()
    for path in paths:
        relative = clean_relative(path)
        if not relative.parts:
            raise ValidationError("Pick folders inside the share, not the whole share")
        try:
            files = list(_files_under(smb, relative))
        except Exception as exc:
            raise ValidationError(f"Could not read '{relative}': {exc}") from exc
        for remote, rel, file_size in files:
            if rel in seen:
                continue
            seen.add(rel)
            if already_here(Path(*rel.parts)):
                skipped += 1
                continue
            todo.append((remote, rel, file_size))
            size += file_size
    return {"todo": todo, "files": len(todo), "bytes": size, "skipped": skipped}


def copy_file(smb, remote: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(f".{target.name}{intake.PARTIAL_SUFFIX}")
    try:
        with smb.open_file(remote, mode="rb") as src, open(partial, "wb") as dst:
            while True:
                block = src.read(CHUNK)
                if not block:
                    break
                dst.write(block)
        os.replace(partial, target)
    finally:
        if partial.exists():
            partial.unlink()


_job_lock = threading.Lock()
_job: Dict = {"running": False}


def status() -> Dict:
    with _job_lock:
        return {k: (list(v) if isinstance(v, list) else v) for k, v in _job.items()}


def start_copy(paths: List[str], by: str) -> Dict:
    with _job_lock:
        if _job.get("running"):
            raise ConflictError("A copy from Carbon is already running")
    found = plan(paths)
    if not found["files"]:
        raise ValidationError(
            f"Nothing new to copy ({found['skipped']} files are already in intake or processed)"
        )
    with _job_lock:
        if _job.get("running"):
            raise ConflictError("A copy from Carbon is already running")
        _job.clear()
        _job.update(
            running=True,
            started_by=by,
            started_at=time.time(),
            finished_at=None,
            paths=list(paths),
            total=found["files"],
            bytes_total=found["bytes"],
            skipped=found["skipped"],
            done=0,
            failed=0,
            bytes_done=0,
            current=None,
            errors=[],
        )
    thread = threading.Thread(target=_run, args=(found["todo"],), name="carbon-copy", daemon=True)
    thread.start()
    return status()


def _run(todo: List[Tuple[str, PurePosixPath, int]]) -> None:
    root = intake.intake_root()
    try:
        smb = connect()
        for remote, relative, size in todo:
            with _job_lock:
                _job["current"] = str(relative)
            try:
                copy_file(smb, remote, root / Path(*relative.parts))
                with _job_lock:
                    _job["done"] += 1
                    _job["bytes_done"] += size
            except Exception as exc:
                log.warning("carbon_copy_file_failed", error=type(exc).__name__)
                with _job_lock:
                    _job["failed"] += 1
                    if len(_job["errors"]) < MAX_ERRORS:
                        _job["errors"].append(f"{relative}: {type(exc).__name__}: {exc}")
    except Exception as exc:
        log.error("carbon_copy_failed", error=str(exc))
        with _job_lock:
            _job["errors"].append(f"Copy stopped: {exc}")
    finally:
        with _job_lock:
            _job["running"] = False
            _job["current"] = None
            _job["finished_at"] = time.time()
            done, failed = _job["done"], _job["failed"]
        log.info("carbon_copy_finished", done=done, failed=failed)
        intake_progress.clear_cache()
