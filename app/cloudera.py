"""Cloudera AI (CML) API v2 client -- just enough to start a job run.

The de-identification stack is ~3GB of ML dependencies split across two
virtualenvs. None of that belongs in the API Application, which has to
stay small and responsive, so on Cloudera the API does not do the work:
it marks the row and asks the platform to start the de-identification
**Job**, which drains the queue.

Deliberately hand-rolled over httpx rather than pulling in `cmlapi`: this
is one POST, and the SDK is a large transitive dependency for the web
process to carry for a single call.

## Configuration

Inside a CML session/job/application the platform injects CDSW_* vars, so
in practice only the job id has to be set by hand:

| var | default | what it is |
|---|---|---|
| `CML_DEID_JOB_ID` | — | **required**; the Job's id, from its URL |
| `CML_PROJECT_ID` | `$CDSW_PROJECT_ID` | injected by the platform |
| `CML_API_KEY` | `$CDSW_APIV2_KEY` | injected; a legacy API key will NOT work |
| `CML_API_URL` | derived from `$CDSW_DOMAIN` | `https://<domain>/api/v2` |

`CDSW_APIV2_KEY` is only injected when the workspace has API v2 enabled
for the project. If it is missing, mint a key in the CML UI (User
Settings -> API Keys) and set `CML_API_KEY` explicitly.
"""
import os
from typing import Dict, Optional

import httpx

from app.logging_setup import get_logger

log = get_logger(__name__)

# Starting a job run is one small POST. If the control plane is slow
# enough to exceed this, the click has failed as far as the user is
# concerned and retrying beats hanging the request.
CML_TIMEOUT_SECONDS = float(os.environ.get("CML_TIMEOUT_SECONDS", "20"))

# httpx verifies against certifi's bundle, NOT the operating system trust
# store. A workspace fronted by an internal or corporate CA therefore
# fails with "unable to get local issuer certificate" even though curl on
# the same host is perfectly happy -- curl reads the OS store, this does
# not. The two REQUESTS_*/SSL_* names are the de-facto standard and are
# already set in most CML runtimes, so usually nothing needs setting by
# hand; CML_CA_BUNDLE is the explicit override.
CML_CA_BUNDLE = (
    os.environ.get("CML_CA_BUNDLE")
    or os.environ.get("REQUESTS_CA_BUNDLE")
    or os.environ.get("SSL_CERT_FILE")
)


def _tls_verify():
    """What to pass as httpx's `verify`: a CA bundle path, or True/False.

    Turning verification off is opt-in and never the default -- this call
    carries the API key in an Authorization header, so an unverified
    connection hands that key to whoever answers. It exists only for a
    workspace whose CA genuinely cannot be obtained.
    """
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
    """Raised for any failure to reach or command the CML API."""


def _api_url() -> str:
    explicit = os.environ.get("CML_API_URL")
    if explicit:
        return explicit.rstrip("/")

    domain = os.environ.get("CDSW_DOMAIN")
    if domain:
        # CDSW_DOMAIN is the bare host; CDSW_API_URL (which the platform
        # also injects) points at the *v1* API, so it is not usable here.
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
    """Whether a job run could be started right now.

    Used at startup to fail loudly on a misconfigured deployment rather
    than at the moment a user clicks De-identify.
    """
    try:
        _config()
        return True
    except ClouderaError:
        return False


def start_deid_job_run(environment: Optional[Dict[str, str]] = None) -> str:
    """Start a run of the de-identification Job. Returns the run id.

    `environment` overrides env vars for this run only, which is how a
    run is scoped to one file (DEID_FILE_ID) without a second Job.
    """
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
        # Values must be strings; the API rejects a JSON number here.
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
        # A certificate failure here is almost always the internal-CA
        # case, and the raw OpenSSL wording ("unable to get local issuer
        # certificate") does not hint at what to set. Say it once, here.
        if "certificate" in str(exc).lower():
            raise ClouderaError(
                f"Could not reach the Cloudera API: {exc}. The workspace's "
                "certificate was not signed by a CA this process trusts -- "
                "point CML_CA_BUNDLE (or REQUESTS_CA_BUNDLE) at the CA "
                "bundle PEM for your workspace."
            ) from exc
        raise ClouderaError(f"Could not reach the Cloudera API: {exc}") from exc

    if response.status_code >= 400:
        # The body carries the actual reason (bad job id, expired key);
        # truncated because it can be a full HTML error page.
        raise ClouderaError(
            f"Cloudera API returned {response.status_code}: {response.text[:300]}"
        )

    try:
        run_id = response.json().get("id", "")
    except ValueError:
        run_id = ""

    log.info("cml_job_run_started", job_id=config["job_id"], run_id=run_id)
    return run_id
