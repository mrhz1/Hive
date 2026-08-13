import os
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import access_log, cloudera, deid, deid_queue
from app.errors import AppError, app_error_handler, unhandled_error_handler
from app.logging_setup import configure_logging, get_logger
from app.middleware import RequestContextMiddleware
from app.routers import (
    access_log as access_log_router,
    audit_log,
    file_metadata,
    files,
    me,
    patient_applications,
    patient_application_files,
    patients,
    roles,
    users,
)

configure_logging()
log = get_logger(__name__)


def _origin_only(value: str) -> str:
    """`https://host:port` out of whatever was pasted into the variable."""
    cleaned = value.strip()
    if not cleaned or cleaned == "*":
        return cleaned

    parsed = urlparse(cleaned if "//" in cleaned else f"//{cleaned}")
    if not parsed.netloc:
        return ""
    return f"{parsed.scheme or 'https'}://{parsed.netloc}"


def _cors_origins() -> list[str]:
    """Allowed browser origins.

    An origin is scheme + host + port and nothing else, so
    `https://example.org/` and `https://example.org/app` are both misses
    -- and the browser then reports a CORS failure that looks exactly
    like the server ignoring the setting. Trailing slashes and paths are
    trimmed here rather than left to be found out that way.
    """
    configured = os.environ.get("CORS_ORIGINS")
    if configured:
        return [
            origin
            for origin in (_origin_only(o) for o in configured.split(","))
            if origin
        ]

    # The Vite dev server, wherever it landed when 5173 was taken.
    return [
        f"http://{host}:{port}"
        for host in ("localhost", "127.0.0.1")
        for port in range(5173, 5181)
    ]


CORS_ORIGINS = _cors_origins()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Say at boot whether de-identification can actually be dispatched."""
    # A browser will not say which origin it was refused for, and the
    # failure looks identical to the API being down. Printing the list
    # turns 'why the CORS error' into reading one line of the log.
    log.info(
        "cors_origins_allowed",
        origins=CORS_ORIGINS,
        configured=bool(os.environ.get("CORS_ORIGINS")),
    )

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
            deid_queue.request_dispatch()

    yield

    if deid.DEID_BACKEND == "cml_job":
        deid_queue.stop()

    # Whatever is still buffered goes to Hive before the process exits.
    access_log.stop()


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
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
app.include_router(files.router)
app.include_router(file_metadata.router)
app.include_router(patient_application_files.router)
app.include_router(patient_applications.router)
app.include_router(roles.router)
app.include_router(audit_log.router)
app.include_router(access_log_router.router)


@app.get("/health", tags=["meta"])
def health():
    """Liveness only -- deliberately does not touch Hive, so a slow metastore cannot make the app look dead to a health checker."""
    return {"status": "ok"}
