"""Domain exceptions + the handlers that turn them into HTTP responses."""
from fastapi import Request
from fastapi.responses import JSONResponse

from app.logging_setup import get_logger

log = get_logger(__name__)


class AppError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    """Uniqueness violation."""

    status_code = 409
    code = "conflict"


class ValidationError(AppError):
    status_code = 422
    code = "validation_error"


class AuthError(AppError):
    status_code = 401
    code = "unauthenticated"


class PermissionDeniedError(AppError):
    status_code = 403
    code = "permission_denied"


class DatabaseError(AppError):
    """Raised when Hive itself fails, so callers get a clean 503 instead of a raw impyla traceback."""

    status_code = 503
    code = "database_error"


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    log.warning(
        "request_failed",
        error_code=exc.code,
        status_code=exc.status_code,
        detail=exc.message,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "detail": exc.message}},
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled_exception", error=str(exc))
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "internal_error", "detail": "Internal server error"}},
    )
