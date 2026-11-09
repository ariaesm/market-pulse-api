"""Domain exceptions shared across layers.

The API layer maps every :class:`AppError` to a consistent JSON error envelope::

    {"error": {"code": "...", "message": "...", "details": {...}}}
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for errors that should be rendered as structured API errors."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON error envelope for this error."""
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}


class NotFoundError(AppError):
    """A requested resource does not exist."""

    status_code = 404
    code = "not_found"


class SymbolNotFoundError(NotFoundError):
    """The provider does not know the requested symbol."""

    code = "symbol_not_found"


class UnsupportedIntervalError(AppError):
    """The provider cannot serve the requested candle interval."""

    status_code = 422
    code = "unsupported_interval"


class InvalidIndicatorError(AppError):
    """An indicator specification could not be parsed."""

    status_code = 422
    code = "invalid_indicator"


class RuleSyntaxError(AppError):
    """An alert rule expression is malformed."""

    status_code = 422
    code = "invalid_rule"


class ProviderError(AppError):
    """An upstream data provider failed."""

    status_code = 502
    code = "provider_error"


class AuthError(AppError):
    """Missing or invalid API key."""

    status_code = 401
    code = "unauthorized"


class RateLimitedError(AppError):
    """Client exceeded the request rate limit."""

    status_code = 429
    code = "rate_limited"
