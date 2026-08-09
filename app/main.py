import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import cloudera, deid, deid_queue
from app.errors import AppError, app_error_handler, unhandled_error_handler
from app.logging_setup import configure_logging, get_logger
from app.middleware import RequestContextMiddleware
from app.routers import (
    audit_log,
    me,
    patient_applications,
    patient_application_files,
    patients,
    roles,
    users,
)

configure_logging()
log = get_logger(__name__)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Say at boot whether de-identification can actually be dispatched.

    Without this the first symptom of a half-configured cml_job backend
    is a user clicking De-identify and the row going straight to
    'failed' -- with the real reason buried in a background task's log.
    A misconfiguration is not made fatal, though: the rest of the API is
    perfectly usable, and refusing to start would turn a broken feature
    into a broken deployment.
    """
    if deid.DEID_BACKEND == "cml_job" and not cloudera.is_configured():
        log.error(
            "deid_backend_misconfigured",
            backend=deid.DEID_BACKEND,
            detail=(
                "DEID_BACKEND=cml_job but the Cloudera API is not "
                "configured; set CML_DEID_JOB_ID (and CML_API_KEY / "
                "CML_PROJECT_ID if not running inside a CML workload)"
            ),
        )
    else:
        log.info("deid_backend", backend=deid.DEID_BACKEND)
        if deid.DEID_BACKEND == "cml_job":
            # Start the dispatcher now rather than on the first click, so
            # rows left `queued` by a previous process are picked up
            # instead of waiting for someone to notice and re-click.
            deid_queue.request_dispatch()

    yield

    if deid.DEID_BACKEND == "cml_job":
        deid_queue.stop()


app = FastAPI(
    title="Hive Users API",
    description=(
        "FastAPI + HiveServer2 (ORC, ACID). Caller identity is the username "
        "in the REMOTE-USER header; every endpoint requires a "
        "'<model>:<action>' permission granted through the caller's role."
    ),
    lifespan=lifespan,
)

app.add_middleware(RequestContextMiddleware)

# The dashboard is served from a different origin in dev (Vite on 5173).
# Origins come from config, not a hardcoded environment check -- on
# Cloudera AI set CORS_ORIGINS to the deployed app origin.
def _cors_origins() -> list[str]:
    """Allowed browser origins.

    Set CORS_ORIGINS (comma separated) to pin this exactly -- on Cloudera
    AI that should be the deployed app origin and nothing else.

    The default covers localhost AND 127.0.0.1 across the ports Vite
    actually uses: it silently falls back to 5174, 5175, ... when 5173 is
    already taken, and a mismatch here does not look like a CORS error in
    the browser -- the request just fails and the app reports the API as
    unreachable. Allowing the fallback range removes that trap in dev.
    """
    configured = os.environ.get("CORS_ORIGINS")
    if configured:
        return [o.strip() for o in configured.split(",") if o.strip()]

    return [
        f"http://{host}:{port}"
        for host in ("localhost", "127.0.0.1")
        for port in range(5173, 5181)
    ]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # So the browser can read the correlation id off a response.
    expose_headers=["X-Request-ID"],
)

app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(Exception, unhandled_error_handler)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request, exc: RequestValidationError):
    log.warning("request_validation_failed", errors=exc.errors())
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_error",
                "detail": "Request body failed validation",
                "fields": [
                    {"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()
                ],
            }
        },
    )


app.include_router(me.router)
app.include_router(users.router)
app.include_router(patients.router)
app.include_router(patient_application_files.router)
app.include_router(patient_applications.router)
app.include_router(roles.router)
app.include_router(audit_log.router)


@app.get("/health", tags=["meta"])
def health():
    """Liveness only -- deliberately does not touch Hive, so a slow
    metastore cannot make the app look dead to a health checker."""
    return {"status": "ok"}
