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

from app import consent, redcap, redcap_api
from app.audit import record_audit
from app.db import hive_cursor
from app.storage import REPO_ROOT

ACTOR = "redcap-sync"
FILES = {redcap.DICTIONARY: "dictionary.csv", redcap.RECORDS: "records.csv", redcap.LOG: "log.csv"}


def drop_dir() -> Path:
    value = Path(os.environ.get("REDCAP_DROP_DIR", "storage/redcap_drop"))
    return value if value.is_absolute() else REPO_ROOT / value


def fetch(cursor, dataset: str, token: str, kind: str) -> bytes:
    if kind == redcap.DICTIONARY:
        return redcap_api.export_dictionary(token)
    if kind == redcap.RECORDS:
        return redcap_api.export_records(token)
    # only new log entries; the importer also skips repeats
    return redcap_api.export_log(token, since=redcap.last_log_time(cursor, dataset))


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
    print(f"mode: REDCap API at {redcap_api.url()}")
    failed = 0
    consent_token = redcap_api.token(redcap_api.CONSENT)
    if consent_token:
        print("consent matrix (9.5.1)")
        try:
            data = redcap_api.export_records(consent_token, raw=False)
            result = consent.import_file(cursor, "consent.csv", data, True, ACTOR)
            print(f"  {result.counts}")
        except Exception as exc:
            failed += 1
            print(f"  FAILED: {type(exc).__name__}: {exc}")
    datasets = redcap_api.datasets()
    if not datasets:
        print("  nothing to do: REDCAP_DATASETS is empty")
    for dataset, token in datasets:
        field = redcap_api.patient_field(dataset)
        print(f"dataset {dataset}" + (f" (patient code field: {field})" if field else ""))
        if not token:
            failed += 1
            print(f"  skipped: REDCAP_TOKEN_{dataset.upper()} is not set")
            continue
        for kind in redcap.KINDS:
            try:
                data = fetch(cursor, dataset, token, kind)
                result = redcap.run_import(cursor, kind, dataset, f"{kind}.csv", data, True, ACTOR, field)
            except Exception as exc:
                failed += 1
                print(f"  {kind:<10} FAILED: {type(exc).__name__}: {exc}")
                continue
            report(result)
            if result.applied:
                audit(result, "api")
    return failed


def main():
    failed = 0
    with hive_cursor() as cursor:
        if redcap_api.configured():
            failed = sync_api(cursor)
        else:
            sync_files(cursor)
    if failed:
        sys.exit(1)  # the Cloudera Job shows as failed


if __name__ == "__main__":
    main()
