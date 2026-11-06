"""Single error shape: {"error": {"code", "message", "request_id"}} (docs/api.md section 1)."""

from __future__ import annotations

import contextvars
import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("dce.errors")

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="req_none")

STATUS_CODES: dict[str, int] = {
    "UNAUTHENTICATED": 401,
    "FORBIDDEN": 403,
    "SELF_APPROVAL_NOT_ALLOWED": 403,
    "QUOTA_EXCEEDED": 429,
    "RATE_LIMITED": 429,
    "VALIDATION_FAILED": 422,
    "NOT_FOUND": 404,
    "CONFLICT": 409,
    "INVALID_STATE": 409,
    "UNAVAILABLE": 503,
    "INTERNAL": 500,
}


class AppError(Exception):
    def __init__(self, code: str, message: str, *, status: int | None = None, headers: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status or STATUS_CODES[code]
        self.headers = headers


def error_body(code: str, message: str) -> dict[str, dict[str, str]]:
    return {"error": {"code": code, "message": message, "request_id": request_id_var.get()}}


_HTTP_CODE_MAP = {401: "UNAUTHENTICATED", 403: "FORBIDDEN", 404: "NOT_FOUND", 409: "CONFLICT", 429: "RATE_LIMITED"}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(error_body(exc.code, exc.message), status_code=exc.status, headers=exc.headers)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODE_MAP.get(exc.status_code, "INTERNAL" if exc.status_code >= 500 else "VALIDATION_FAILED")
        message = exc.detail if isinstance(exc.detail, str) and exc.status_code < 500 else "Request failed."
        return JSONResponse(error_body(code, message), status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(p) for p in first.get("loc", ()) if p != "body")
        message = f"Invalid field: {loc}" if loc else "Invalid request body."
        return JSONResponse(error_body("VALIDATION_FAILED", message), status_code=422)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled error request_id=%s type=%s", request_id_var.get(), type(exc).__name__, exc_info=exc)
        return JSONResponse(error_body("INTERNAL", "Internal error."), status_code=500)


def new_request_id() -> str:
    return "req_" + uuid.uuid4().hex[:16]
