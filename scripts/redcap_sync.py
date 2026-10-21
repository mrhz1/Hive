import os
import sys
from pathlib import Path


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
    candidates += [cwd, cwd.parent, Path("/home/cdsw/Backend")]
    for candidate in candidates:
        if (candidate / "app" / "redcap.py").is_file():
            return candidate
    raise RuntimeError("Cannot locate the repo root; set HIVE_REPO_ROOT")


ROOT = _repo_root()
sys.path.insert(0, str(ROOT))

from app import consent, redcap
from app.audit import record_audit
from app.db import hive_cursor
from app.storage import REPO_ROOT

ACTOR = "redcap-sync"
FILES = {redcap.DICTIONARY: "dictionary.csv", redcap.RECORDS: "records.csv", redcap.LOG: "log.csv"}
API_CONTENT = {
    redcap.DICTIONARY: {"content": "metadata"},
    redcap.RECORDS: {"content": "record", "type": "flat", "rawOrLabel": "raw"},
    redcap.LOG: {"content": "log"},
}


def drop_dir() -> Path:
    value = Path(os.environ.get("REDCAP_DROP_DIR", "storage/redcap_drop"))
    return value if value.is_absolute() else REPO_ROOT / value


def datasets_from_api():
    names = [n.strip().lower() for n in os.environ.get("REDCAP_DATASETS", "").split(",") if n.strip()]
    return [(name, os.environ.get(f"REDCAP_TOKEN_{name.upper()}", "")) for name in names]


def fetch(token: str, kind: str) -> bytes:
    import httpx

    response = httpx.post(
        os.environ["REDCAP_URL"],
        data={"token": token, "format": "csv", "returnFormat": "json", **API_CONTENT[kind]},
        timeout=float(os.environ.get("REDCAP_TIMEOUT_SECONDS", "120")),
    )
    response.raise_for_status()
    return response.content


def report(result):
    status = "imported" if result.applied else "nothing new"
    print(f"  {result.kind:<10} {status:<12} {result.counts}")
    for line in result.problems + result.notes:
        print(f"             - {line}")


def audit(result, source):
    record_audit(
        action="CREATE",
        entity_type=f"redcap_{result.kind}",
        entity_id=result.dataset,
        user_id=ACTOR,
        old_values=None,
        new_values={"source": source, "counts": result.counts},
    )


def sync_files(cursor):
    folder = drop_dir()
    print(f"mode: files (simulated REDCap) from {folder}")
    if not folder.is_dir():
        print("  nothing to do: the folder does not exist")
        return
    consent_file = folder / "consent.csv"
    if consent_file.is_file():
        result = consent.import_file(cursor, consent_file.name, consent_file.read_bytes(), True, ACTOR)
        print(f"consent matrix: {result.counts}")
    for dataset_dir in sorted(p for p in folder.iterdir() if p.is_dir()):
        print(f"dataset {dataset_dir.name}")
        for kind in redcap.KINDS:
            path = dataset_dir / FILES[kind]
            if not path.is_file():
                continue
            result = redcap.run_import(cursor, kind, dataset_dir.name, path.name, path.read_bytes(), True, ACTOR)
            report(result)
            if result.applied:
                audit(result, f"file {path}")


def sync_api(cursor):
    print(f"mode: REDCap API at {os.environ['REDCAP_URL']}")
    for dataset, token in datasets_from_api():
        print(f"dataset {dataset}")
        if not token:
            print(f"  skipped: REDCAP_TOKEN_{dataset.upper()} is not set")
            continue
        for kind in redcap.KINDS:
            try:
                data = fetch(token, kind)
            except Exception as exc:
                print(f"  {kind:<10} FAILED to fetch: {type(exc).__name__}: {exc}")
                continue
            result = redcap.run_import(cursor, kind, dataset, f"{kind}.csv", data, True, ACTOR)
            report(result)
            if result.applied:
                audit(result, "api")


def main():
    with hive_cursor() as cursor:
        if redcap.mode() == "api":
            sync_api(cursor)
        else:
            sync_files(cursor)


if __name__ == "__main__":
    main()
