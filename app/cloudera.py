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


class ClouderaCapacityError(ClouderaError):
    """The control plane refused the run for want of capacity, not because
    anything is wrong with it.

    Separate from ClouderaError because the two want opposite handling: a
    bad job id will never succeed and the row should say so, while a
    quota rejection means "not now" and the row should stay claimable so
    the sweep run picks it up once capacity frees.
    """


# 409 is what CML returns for "out of quota: CPU request limit reached",
# 429 for rate limiting, and 5xx is the control plane having a bad day.
# None of them say the request was wrong.
_RETRYABLE_STATUS = (409, 429, 500, 502, 503, 504)

# CML will not run two runs of one Job at once, and does not always use
# 409 to say so -- the refusal can arrive as a 400 whose body is the only
# thing that identifies it. It means exactly what a quota rejection means
# ("not now"), so it must not mark the row failed: the run already in
# flight re-queries for `queued` rows and will absorb this file.
_BUSY_PHRASES = (
    "already active",  # the exact wording CML uses: "job run for job <id>
    # already active, code 9", and it arrives as a 400
    "already running",
    "already in progress",
    "another run",
    "run in progress",
    "concurrent",
    "is running",
    "skipped",
)

# Substrings of a CML run status that mean the run is over, whatever the
# outcome. Matched loosely because the platform prefixes them
# (ENGINE_SUCCEEDED, ENGINE_TIMEDOUT) and the exact set varies by
# version -- an unrecognised status is treated as still-running, which
# errs towards waiting rather than towards starting a second run.
_TERMINAL_RUN_STATES = (
    "succeeded",
    "failed",
    "stopped",
    "timedout",
    "timed_out",
    "killed",
    "cancelled",
    "canceled",
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

    if response.status_code in _RETRYABLE_STATUS:
        raise ClouderaCapacityError(
            f"Cloudera API returned {response.status_code}: {response.text[:300]}"
        )

    if response.status_code >= 400:
        # The body carries the actual reason (bad job id, expired key);
        # truncated because it can be a full HTML error page.
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

    # A 200 does not mean the run will execute. CML accepts the request
    # and then skips it when a run of the same Job is already going, so
    # log the state rather than reporting an unconditional success --
    # "dispatched" for a run that never starts is the log line that makes
    # this take an afternoon to find.
    if "skip" in status.lower():
        log.warning(
            "cml_job_run_skipped",
            job_id=config["job_id"],
            run_id=run_id,
            status=status,
            detail="a run of this Job is already active; the row stays "
            "queued for the active run or the sweep to pick up",
        )
        return run_id

    log.info(
        "cml_job_run_started", job_id=config["job_id"], run_id=run_id, status=status
    )
    return run_id


def get_job_run_status(run_id: str) -> str:
    """Current status of one run, or "" when it cannot be determined.

    Best effort by design: this is used to decide whether the previous
    run has finished, and an unreadable answer must not be mistaken for
    "finished" -- the caller treats "" as still-running and waits.
    """
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
