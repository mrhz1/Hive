"""REDCap API client (protocol 9.1.12, 9.1.15, 9.5).

Settings (environment, set on Cloudera only):
  REDCAP_URL                      e.g. https://redcapexternal.research.sickkids.ca/api/
  REDCAP_DATASETS                 comma list of clinical datasets, e.g. chd_clinical
  REDCAP_TOKEN_<DATASET>          one API token per dataset (REDCap project)
  REDCAP_PATIENT_FIELD_<DATASET>  field holding the patient (UBRS) code; default = record ID
  REDCAP_TOKEN_CONSENT            consent & contact matrix project (9.5.1), optional
  REDCAP_TOKEN_FOLLOWUP           periodic follow-up survey project (9.5.3), optional
  REDCAP_FOLLOWUP_INSTRUMENT      survey instrument whose link goes in the follow-up list
  REDCAP_TIMEOUT_SECONDS          default 120
"""

import os
from typing import Optional

from app.logging_setup import get_logger

log = get_logger(__name__)

CONSENT = "consent"
FOLLOWUP = "followup"


class RedcapError(Exception):
    pass


def url() -> str:
    return (os.environ.get("REDCAP_URL") or "").strip()


def configured() -> bool:
    return bool(url())


def datasets():
    names = [n.strip().lower() for n in os.environ.get("REDCAP_DATASETS", "").split(",") if n.strip()]
    return [(name, token(name)) for name in names]


def token(name: str) -> str:
    return (os.environ.get(f"REDCAP_TOKEN_{name.upper()}") or "").strip()


def patient_field(dataset: str) -> Optional[str]:
    value = (os.environ.get(f"REDCAP_PATIENT_FIELD_{dataset.upper()}") or "").strip().lower()
    return value or None


def followup_instrument() -> Optional[str]:
    return (os.environ.get("REDCAP_FOLLOWUP_INSTRUMENT") or "").strip() or None


def _message(response) -> str:
    try:
        body = response.json()
        if isinstance(body, dict) and body.get("error"):
            return str(body["error"])
    except ValueError:
        pass
    return response.text[:300]


def call(api_token: str, content: str, **params) -> bytes:
    """POST one API request. Never logs the token or the response body."""
    import httpx

    if not configured():
        raise RedcapError("REDCAP_URL is not set")
    if not api_token:
        raise RedcapError("no API token")
    data = {"token": api_token, "content": content, "returnFormat": "json"}
    data.setdefault("format", "csv")
    data.update({k: v for k, v in params.items() if v is not None})
    try:
        response = httpx.post(
            url(), data=data, timeout=float(os.environ.get("REDCAP_TIMEOUT_SECONDS", "120"))
        )
    except httpx.HTTPError as exc:
        raise RedcapError(f"cannot reach REDCap: {type(exc).__name__}: {exc}") from None
    if response.status_code != 200:
        raise RedcapError(f"REDCap said {response.status_code}: {_message(response)}")
    return response.content


def export_dictionary(api_token: str) -> bytes:
    return call(api_token, "metadata")


def export_records(api_token: str, raw: bool = True, fields=None) -> bytes:
    extra = {f"fields[{i}]": f for i, f in enumerate(fields or [])}
    return call(api_token, "record", type="flat", rawOrLabel="raw" if raw else "label",
                rawOrLabelHeaders="raw", exportCheckboxLabel="false", **extra)


def export_log(api_token: str, since: Optional[str] = None) -> bytes:
    """since: 'YYYY-MM-DD HH:MM' (REDCap server time); only newer entries."""
    return call(api_token, "log", beginTime=since)


def survey_link(api_token: str, record: str, instrument: str, instance: int = 1) -> str:
    body = call(api_token, "surveyLink", format="json", record=record,
                instrument=instrument, repeat_instance=str(instance))
    return body.decode("utf-8").strip()
