import os
import sys
from pathlib import Path

APPLY = False
LIMIT = 0


def _repo_root():
    here = globals().get("__file__")
    candidates = []
    if here:
        own = Path(here).resolve().parent
        candidates += [own, own.parent]
    for var in ("HIVE_REPO_ROOT", "CDSW_PROJECT_DIR"):
        if os.environ.get(var):
            candidates.append(Path(os.environ[var]))
    cwd = Path.cwd().resolve()
    candidates += [cwd, cwd.parent, Path("/home/cdsw/Backend"), Path("/home/cdsw")]
    for candidate in candidates:
        if (candidate / "app" / "file_metadata.py").is_file():
            return candidate
    raise RuntimeError("Cannot locate the repo root; set HIVE_REPO_ROOT")


sys.path.insert(0, str(_repo_root()))

from app.crud import file_metadata as metadata_crud
from app.crud import patient_application_files as files_crud
from app.db import hive_cursor
from app.file_metadata import extract
from app.purge import is_deleted_file
from app.schemas import FileMetadataCreate


def main():
    print("mode: " + ("WRITE" if APPLY else "dry run (set APPLY = True to write)"))
    with hive_cursor() as cursor:
        files = [f for f in files_crud.list_files(cursor) if not is_deleted_file(f)]
        have = {m.file_id for m in metadata_crud.list_metadata(cursor)}
        missing = [f for f in files if f.id not in have]
        print(f"{len(files)} files, {len(missing)} without metadata")
        if LIMIT:
            missing = missing[:LIMIT]

        counts = {"ok": 0, "failed": 0, "unsupported": 0, "write_error": 0}
        for number, record in enumerate(missing, 1):
            path = Path(record.file_path or "")
            file_type, metadata, status, error = extract(path, record.file_extension or "")
            line = f"[{number}/{len(missing)}] {record.id} {file_type} {status} {len(metadata)} fields"
            if error:
                line += f" ({error[:120]})"
            if APPLY:
                try:
                    metadata_crud.create_metadata(
                        cursor,
                        FileMetadataCreate(
                            file_id=record.id,
                            file_type=file_type,
                            metadata=metadata,
                            status=status,
                            error=error,
                        ),
                    )
                except Exception as exc:
                    counts["write_error"] += 1
                    print(f"{line}  WRITE FAILED: {type(exc).__name__}: {str(exc)[:300]}")
                    continue
            counts[status] = counts.get(status, 0) + 1
            print(line)
        print(f"\nsummary: {counts}")


if __name__ == "__main__":
    main()
