"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI

from market_pulse import __version__
from market_pulse.api.container import Container, build_container
from market_pulse.api.deps import require_api_key
from market_pulse.api.errors import register_error_handlers
from market_pulse.api.middleware import RateLimitMiddleware, RequestContextMiddleware
from market_pulse.api.routes import alerts, health, market, ws
from market_pulse.cache import Cache
from market_pulse.config import Settings
from market_pulse.providers import MarketDataProvider

DESCRIPTION = """
Market data service: OHLCV candles, technical indicators computed from scratch,
rule-based signals and alert rules streamed over WebSocket.

The default data provider serves **synthetic** data bundled with the project.
Nothing returned by this API is financial advice.
"""

TAGS_METADATA = [
    {"name": "health", "description": "Liveness and component status."},
    {"name": "market data", "description": "Symbols and OHLCV candles."},
    {"name": "indicators", "description": "SMA, EMA, RSI, MACD, Bollinger Bands, ATR, Stochastic."},
    {"name": "signals", "description": "Simple rule-based signals. Not financial advice."},
    {"name": "alerts", "description": "Alert rules and the WebSocket alert stream."},
]


def create_app(
    settings: Settings | None = None,
    *,
    provider: MarketDataProvider | None = None,
    cache: Cache | None = None,
) -> FastAPI:
    """Build a configured FastAPI app. ``provider``/``cache`` may be injected for tests."""
    settings = settings or Settings.from_env()
    container = build_container(settings, provider=provider, cache=cache)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if settings.alert_eval_enabled:
            container.evaluator.start()
        try:
            yield
        finally:
            await container.aclose()

    app = FastAPI(
        title="market-pulse-api",
        version=__version__,
        description=DESCRIPTION,
        openapi_tags=TAGS_METADATA,
        license_info={"name": "MIT", "identifier": "MIT"},
        lifespan=lifespan,
    )
    app.state.container = container
    register_error_handlers(app)

    if container.limiter is not None:
        app.add_middleware(RateLimitMiddleware, limiter=container.limiter)
    app.add_middleware(RequestContextMiddleware)  # outermost: also wraps 429s

    app.include_router(health.router)
    v1 = APIRouter(prefix="/v1", dependencies=[Depends(require_api_key)])
    v1.include_router(market.router)
    v1.include_router(alerts.router)
    app.include_router(v1)
    # WebSocket auth is handled inside the endpoint (HTTP security deps do not apply).
    app.include_router(ws.router, prefix="/v1")
    return app


def get_container_from_app(app: FastAPI) -> Container:
    """Convenience accessor used by tests and scripts."""
    container: Container = app.state.container
    return container
