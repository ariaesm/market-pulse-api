"""Exception handlers producing the consistent ``{"error": {...}}`` envelope."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from market_pulse.errors import AppError

logger = logging.getLogger(__name__)

_HTTP_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    429: "rate_limited",
}


def _envelope(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


async def app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Render domain errors."""
    assert isinstance(exc, AppError)
    return JSONResponse(exc.to_dict(), status_code=exc.status_code)


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Render request validation failures (422) without leaking internal objects."""
    assert isinstance(exc, RequestValidationError)
    errors = [
        {"loc": list(err.get("loc", ())), "msg": err.get("msg", ""), "type": err.get("type", "")}
        for err in exc.errors()
    ]
    return JSONResponse(
        _envelope("validation_error", "request validation failed", {"errors": errors}),
        status_code=422,
    )


async def http_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Render framework HTTP errors such as unknown routes (404) or 405."""
    assert isinstance(exc, StarletteHTTPException)
    code = _HTTP_CODES.get(exc.status_code, "http_error")
    return JSONResponse(
        _envelope(code, str(exc.detail)),
        status_code=exc.status_code,
        headers=getattr(exc, "headers", None),
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Last-resort handler: log and hide internals."""
    logger.exception("unhandled error", extra={"path": request.url.path})
    return JSONResponse(_envelope("internal_error", "internal server error"), status_code=500)


def register_error_handlers(app: FastAPI) -> None:
    """Attach all handlers to ``app``."""
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
