"""Wiring of application services (framework independent, so it is testable offline)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from market_pulse.alerts import AlertStore
from market_pulse.cache import Cache, build_cache
from market_pulse.config import Settings
from market_pulse.evaluator import AlertEvaluator
from market_pulse.providers import BinanceProvider, CSVProvider, MarketDataProvider
from market_pulse.providers.cached import CachedProvider
from market_pulse.ratelimit import RateLimiter
from market_pulse.streaming import AlertBroker


@dataclass
class Container:
    """All long-lived services used by request handlers and background tasks."""

    settings: Settings
    provider: MarketDataProvider
    cache: Cache
    store: AlertStore
    broker: AlertBroker
    evaluator: AlertEvaluator
    limiter: RateLimiter | None
    started_at: float = field(default_factory=time.monotonic)

    @property
    def uptime_seconds(self) -> float:
        """Seconds since the container was built."""
        return round(time.monotonic() - self.started_at, 3)

    async def aclose(self) -> None:
        """Stop background work and release resources."""
        await self.evaluator.stop()
        await self.provider.aclose()
        await self.cache.close()


def build_provider(settings: Settings) -> MarketDataProvider:
    """Instantiate the raw provider selected by ``settings.data_provider``."""
    if settings.data_provider == "binance":
        return BinanceProvider(
            settings.binance_base_url,
            settings.binance_symbols,
            timeout=settings.provider_timeout_seconds,
        )
    return CSVProvider(settings.data_dir)


def build_container(
    settings: Settings,
    *,
    provider: MarketDataProvider | None = None,
    cache: Cache | None = None,
) -> Container:
    """Create the service graph; ``provider``/``cache`` can be injected for tests."""
    cache = cache if cache is not None else build_cache(settings)
    raw = provider if provider is not None else build_provider(settings)
    cached = CachedProvider(raw, cache, settings.cache_ttl_seconds)
    store = AlertStore()
    broker = AlertBroker()
    evaluator = AlertEvaluator(
        cached,
        store,
        broker,
        interval_seconds=settings.alert_eval_interval_seconds,
        lookback=settings.alert_lookback,
    )
    limiter = (
        RateLimiter(settings.rate_limit_per_minute, settings.rate_limit_burst)
        if settings.rate_limit_enabled
        else None
    )
    return Container(settings, cached, cache, store, broker, evaluator, limiter)
