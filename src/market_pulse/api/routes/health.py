"""Health endpoint (unauthenticated, not rate limited)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from market_pulse import __version__
from market_pulse.api.container import Container
from market_pulse.api.deps import get_container
from market_pulse.api.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Service health")
async def health(container: Container = Depends(get_container)) -> HealthResponse:
    """Report liveness and the status of internal components."""
    settings = container.settings
    return HealthResponse(
        version=__version__,
        provider=container.provider.name,
        synthetic_data=container.provider.synthetic,
        cache_backend=settings.cache_backend,
        auth_enabled=settings.auth_enabled,
        alert_evaluator_running=container.evaluator.running,
        alert_rules=len(container.store),
        websocket_subscribers=container.broker.subscriber_count,
        uptime_seconds=container.uptime_seconds,
    )
