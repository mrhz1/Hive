import os
from typing import Dict, Optional

import httpx

from app.logging_setup import get_logger

log = get_logger(__name__)

CML_TIMEOUT_SECONDS = float(os.environ.get("CML_TIMEOUT_SECONDS", "20"))

CML_CA_BUNDLE = (
    os.environ.get("CML_CA_BUNDLE")
    or os.environ.get("REQUESTS_CA_BUNDLE")
    or os.environ.get("SSL_CERT_FILE")
)


def _tls_verify():
    disabled = os.environ.get("CML_VERIFY_TLS", "true").strip().lower() in (
        "0",
        "false",
        "no",
        "off",
    )
    if disabled:
        log.warning("cml_tls_verification_disabled")
        return False
    return CML_CA_BUNDLE or True


class ClouderaError(Exception):
    pass


class ClouderaCapacityError(ClouderaError):
    pass


_RETRYABLE_STATUS = (409, 429, 500, 502, 503, 504)

_BUSY_PHRASES = (
    "already active",
    "already running",
    "already in progress",
    "another run",
    "run in progress",
    "concurrent",
    "is running",
    "skipped",
)

_TERMINAL_RUN_STATES = (
    "succeeded",
    "failed",
    "stopped",
    "timedout",
    "timed_out",
    "killed",
    "cancelled",
    "canceled",
    "skipped",
)


def is_terminal_run_status(status: str) -> bool:
    lowered = (status or "").lower()
    return any(state in lowered for state in _TERMINAL_RUN_STATES)


def _is_busy_response(body: str) -> bool:
    lowered = body.lower()
    return any(phrase in lowered for phrase in _BUSY_PHRASES)


def _api_url() -> str:
    explicit = os.environ.get("CML_API_URL")
    if explicit:
        return explicit.rstrip("/")

    domain = os.environ.get("CDSW_DOMAIN")
    if domain:
        return f"https://{domain}/api/v2"

    raise ClouderaError(
        "Cloudera API URL is unknown: set CML_API_URL (or run inside a "
        "CML workload, which injects CDSW_DOMAIN)"
    )


def _config() -> Dict[str, str]:
    project_id = os.environ.get("CML_PROJECT_ID") or os.environ.get("CDSW_PROJECT_ID")
    api_key = os.environ.get("CML_API_KEY") or os.environ.get("CDSW_APIV2_KEY")
    job_id = os.environ.get("CML_DEID_JOB_ID")

    missing = [
        name
        for name, value in (
            ("CML_PROJECT_ID / CDSW_PROJECT_ID", project_id),
            ("CML_API_KEY / CDSW_APIV2_KEY", api_key),
            ("CML_DEID_JOB_ID", job_id),
        )
        if not value
    ]
    if missing:
        raise ClouderaError(
            "Cloudera job dispatch is not configured; missing: " + ", ".join(missing)
        )

    return {
        "url": _api_url(),
        "project_id": project_id,
        "api_key": api_key,
        "job_id": job_id,
    }


def is_configured() -> bool:
    try:
        _config()
        return True
    except ClouderaError:
        return False


def start_deid_job_run(environment: Optional[Dict[str, str]] = None) -> str:
    config = _config()
    url = (
        f"{config['url']}/projects/{config['project_id']}"
        f"/jobs/{config['job_id']}/runs"
    )

    payload = {
        "project_id": config["project_id"],
        "job_id": config["job_id"],
    }
    if environment:
        payload["environment"] = {k: str(v) for k, v in environment.items()}

    try:
        response = httpx.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {config['api_key']}"},
            timeout=CML_TIMEOUT_SECONDS,
            verify=_tls_verify(),
        )
    except httpx.HTTPError as exc:
        if "certificate" in str(exc).lower():
            raise ClouderaError(
                f"Could not reach the Cloudera API: {exc}. The workspace's "
                "certificate was not signed by a CA this process trusts -- "
                "point CML_CA_BUNDLE (or REQUESTS_CA_BUNDLE) at the CA "
                "bundle PEM for your workspace."
            ) from exc
        raise ClouderaError(f"Could not reach the Cloudera API: {exc}") from exc

    if response.status_code in _RETRYABLE_STATUS:
        raise ClouderaCapacityError(
            f"Cloudera API returned {response.status_code}: {response.text[:300]}"
        )

    if response.status_code >= 400:
        detail = f"Cloudera API returned {response.status_code}: {response.text[:300]}"
        if _is_busy_response(response.text):
            raise ClouderaCapacityError(detail)
        raise ClouderaError(detail)

    try:
        body = response.json()
    except ValueError:
        body = {}

    run_id = body.get("id", "") if isinstance(body, dict) else ""
    status = str(body.get("status", "")) if isinstance(body, dict) else ""

    if "skip" in status.lower():
        raise ClouderaCapacityError(
            f"Cloudera skipped the run for job {config['job_id']}: a run is "
            f"already active (status {status!r}, run {run_id or 'unnumbered'})"
        )

    log.info(
        "cml_job_run_started", job_id=config["job_id"], run_id=run_id, status=status
    )
    return run_id


def get_job_run_status(run_id: str) -> str:
    if not run_id:
        return ""

    config = _config()
    url = (
        f"{config['url']}/projects/{config['project_id']}"
        f"/jobs/{config['job_id']}/runs/{run_id}"
    )

    try:
        response = httpx.get(
            url,
            headers={"Authorization": f"Bearer {config['api_key']}"},
            timeout=CML_TIMEOUT_SECONDS,
            verify=_tls_verify(),
        )
    except httpx.HTTPError as exc:
        log.warning("cml_job_run_status_unreachable", run_id=run_id, error=str(exc))
        return ""

    if response.status_code >= 400:
        log.warning(
            "cml_job_run_status_error",
            run_id=run_id,
            status_code=response.status_code,
            body=response.text[:200],
        )
        return ""

    try:
        body = response.json()
    except ValueError:
        return ""

    return str(body.get("status", "")) if isinstance(body, dict) else ""
