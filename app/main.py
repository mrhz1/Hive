import os

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.errors import AppError, app_error_handler, unhandled_error_handler
from app.logging_setup import configure_logging, get_logger
from app.middleware import RequestContextMiddleware
from app.routers import audit_log, customer_files, customers, me, roles, users

configure_logging()
log = get_logger(__name__)

app = FastAPI(
    title="Hive Users API",
    description=(
        "FastAPI + HiveServer2 (ORC, ACID). Caller identity is supplied via "
        "the X-User-Id header; every endpoint requires a '<model>:<action>' "
        "permission granted through the caller's role."
    ),
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
app.include_router(customers.router)
app.include_router(customer_files.router)
app.include_router(roles.router)
app.include_router(audit_log.router)


@app.get("/health", tags=["meta"])
def health():
    """Liveness only -- deliberately does not touch Hive, so a slow
    metastore cannot make the app look dead to a health checker."""
    return {"status": "ok"}
