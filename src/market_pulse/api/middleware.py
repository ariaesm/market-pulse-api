"""Pure ASGI middleware (depends only on Starlette, which FastAPI builds on)."""

from __future__ import annotations

import logging
import time
import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from market_pulse.errors import RateLimitedError
from market_pulse.ratelimit import RateLimiter

logger = logging.getLogger("market_pulse.access")

DEFAULT_EXEMPT_PATHS: frozenset[str] = frozenset(
    {"/health", "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}
)


def client_key(scope: Scope) -> str:
    """Identify a client by API key when present, otherwise by remote address."""
    headers = Headers(scope=scope)
    api_key = headers.get("x-api-key")
    if api_key:
        return f"key:{api_key}"
    client = scope.get("client")
    return f"ip:{client[0]}" if client else "ip:unknown"


class RateLimitMiddleware:
    """Reject HTTP requests over the limit with a 429 JSON error envelope."""

    def __init__(
        self,
        app: ASGIApp,
        limiter: RateLimiter,
        exempt_paths: frozenset[str] = DEFAULT_EXEMPT_PATHS,
    ) -> None:
        self.app = app
        self.limiter = limiter
        self.exempt_paths = exempt_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in self.exempt_paths:
            await self.app(scope, receive, send)
            return
        decision = self.limiter.check(client_key(scope))
        rate_headers = {
            "X-RateLimit-Limit": str(decision.limit),
            "X-RateLimit-Remaining": str(decision.remaining),
        }
        if not decision.allowed:
            error = RateLimitedError(
                "rate limit exceeded", details={"retry_after": decision.retry_after_header}
            )
            response = JSONResponse(
                error.to_dict(),
                status_code=error.status_code,
                headers={**rate_headers, "Retry-After": decision.retry_after_header},
            )
            await response(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in rate_headers.items():
                    headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_headers)


class RequestContextMiddleware:
    """Attach an ``X-Request-ID`` and emit one structured access-log line per request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = Headers(scope=scope).get("x-request-id") or uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        status_code = 500
        start = time.perf_counter()

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            logger.info(
                "request",
                extra={
                    "request_id": request_id,
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "status": status_code,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                },
            )
