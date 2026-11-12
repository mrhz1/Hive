"""Read-only REDCap connection and rights check. Run on the org machine / Cloudera.

    python scripts/redcap_check.py

Uses the same settings as redcap_sync.py (REDCAP_URL, REDCAP_DATASETS,
REDCAP_TOKEN_<DATASET>, REDCAP_PATIENT_FIELD_<DATASET>, REDCAP_TOKEN_CONSENT,
REDCAP_TOKEN_FOLLOWUP, REDCAP_FOLLOWUP_INSTRUMENT). Writes nothing anywhere and
prints only counts, field names and OK/FAIL, never record values or tokens,
so the output is safe to paste back.
"""

import csv
import io
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env.local")
except ImportError:
    pass

from app import redcap_api  # noqa: E402

problems = []


def ok(label, detail=""):
    print(f"  OK    {label}" + (f": {detail}" if detail else ""))


def fail(label, exc):
    problems.append(label)
    print(f"  FAIL  {label}: {exc}")


def rows(data: bytes):
    return list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))


def project(token):
    info = json.loads(redcap_api.call(token, "project", format="json"))
    return (f"PID {info.get('project_id')} '{info.get('project_title')}', "
            f"production={info.get('in_production')}, longitudinal={info.get('is_longitudinal')}, "
            f"repeating={info.get('has_repeating_instruments_or_events')}, "
            f"surveys={info.get('surveys_enabled')}")


def check_dataset(name, token, patient_field=None):
    print(f"\n[{name}]")
    if not token:
        fail("token", f"REDCAP_TOKEN_{name.upper()} is not set")
        return None
    try:
        ok("project", project(token))
    except Exception as exc:
        fail("project info", exc)
        return None
    try:
        fields = rows(redcap_api.export_dictionary(token))
        record_id = fields[0]["field_name"] if fields else "?"
        ids = [f["field_name"] for f in fields if (f.get("identifier") or "").lower() == "y"]
        ok("data dictionary", f"{len(fields)} fields, record ID '{record_id}', identifiers {ids}")
    except Exception as exc:
        fail("data dictionary", exc)
        return None
    names = {f["field_name"] for f in fields}
    if patient_field:
        if patient_field in names:
            ok("patient code field", patient_field)
        else:
            fail("patient code field", f"'{patient_field}' is not in the dictionary")
    try:
        wanted = [record_id] + ([patient_field] if patient_field and patient_field in names else [])
        found = rows(redcap_api.export_records(token, fields=wanted))
        codes = {r.get(patient_field or record_id) for r in found if r.get(patient_field or record_id)}
        instruments = sorted({r.get("redcap_repeat_instrument") for r in found if r.get("redcap_repeat_instrument")})
        ok("records export", f"{len(found)} rows, {len(codes)} distinct patient codes, "
                             f"repeating instruments seen: {instruments or 'none'}")
    except Exception as exc:
        fail("records export (needs Data Export rights = Full Data Set)", exc)
    try:
        since = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M")
        entries = rows(redcap_api.export_log(token, since=since))
        ok("logging export", f"{len(entries)} entries in the last 7 days, columns {list(entries[0]) if entries else '-'}")
    except Exception as exc:
        fail("logging export (needs Logging rights)", exc)
    return fields


def main():
    print(f"REDCap URL: {redcap_api.url() or '(REDCAP_URL not set)'}")
    if not redcap_api.configured():
        sys.exit("Set REDCAP_URL first")
    first = next((t for _, t in redcap_api.datasets() if t), None) or redcap_api.token(redcap_api.CONSENT)
    try:
        ok("reach REDCap", "version " + redcap_api.call(first, "version").decode().strip())
    except Exception as exc:
        fail("reach REDCap", exc)

    for name, token in redcap_api.datasets():
        check_dataset(name, token, redcap_api.patient_field(name))

    consent = redcap_api.token(redcap_api.CONSENT)
    if consent:
        fields = check_dataset("consent", consent)
        if fields:
            print("  consent project fields (to map to: patient code, consent type, status, version, date):")
            print("   ", ", ".join(f["field_name"] for f in fields))
    else:
        print("\n[consent] not set up (REDCAP_TOKEN_CONSENT)")

    followup = redcap_api.token(redcap_api.FOLLOWUP)
    instrument = redcap_api.followup_instrument()
    if followup:
        print("\n[followup]")
        try:
            ok("project", project(followup))
            forms = json.loads(redcap_api.call(followup, "instrument", format="json"))
            ok("instruments", ", ".join(f["instrument_name"] for f in forms))
            if instrument and instrument not in {f["instrument_name"] for f in forms}:
                fail("REDCAP_FOLLOWUP_INSTRUMENT", f"'{instrument}' is not an instrument here")
        except Exception as exc:
            fail("follow-up project", exc)
    else:
        print("\n[followup] not set up (REDCAP_TOKEN_FOLLOWUP)")

    print("\nRESULT:", "all checks passed" if not problems else f"{len(problems)} problem(s): {', '.join(problems)}")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
