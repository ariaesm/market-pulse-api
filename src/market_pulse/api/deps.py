"""FastAPI dependencies: service container access and optional API-key auth."""

from __future__ import annotations

from fastapi import Request, Security
from fastapi.security import APIKeyHeader

from market_pulse.api.container import Container
from market_pulse.auth import is_valid_api_key
from market_pulse.errors import AuthError

api_key_header = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,
    description="Required only when the server is configured with MP_API_KEYS.",
)


def get_container(request: Request) -> Container:
    """Return the service container stored on the application."""
    container: Container = request.app.state.container
    return container


async def require_api_key(request: Request, api_key: str | None = Security(api_key_header)) -> None:
    """Enforce ``X-API-Key`` when auth is enabled; no-op otherwise."""
    settings = get_container(request).settings
    if settings.auth_enabled and not is_valid_api_key(api_key, settings.api_keys):
        raise AuthError("missing or invalid API key")
