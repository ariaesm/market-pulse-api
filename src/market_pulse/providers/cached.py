"""Read-through caching decorator for any :class:`MarketDataProvider`."""

from __future__ import annotations

import logging

import pandas as pd

from market_pulse.cache.base import Cache
from market_pulse.providers.base import (
    MarketDataProvider,
    SymbolInfo,
    candles_from_payload,
    candles_to_payload,
)

logger = logging.getLogger(__name__)


class CachedProvider(MarketDataProvider):
    """Wrap a provider so OHLCV responses are cached for ``ttl`` seconds.

    Cache failures are logged and bypassed: the cache never makes a request fail.
    """

    def __init__(self, inner: MarketDataProvider, cache: Cache, ttl: float) -> None:
        self.inner = inner
        self.cache = cache
        self.ttl = ttl
        self.name = inner.name
        self.synthetic = inner.synthetic

    def _key(self, symbol: str, interval: str, limit: int) -> str:
        return f"ohlcv:{self.inner.name}:{symbol.upper()}:{interval}:{limit}"

    async def list_symbols(self) -> list[SymbolInfo]:
        """Delegate to the wrapped provider (symbol lists are cheap)."""
        return await self.inner.list_symbols()

    async def get_ohlcv(self, symbol: str, interval: str, limit: int) -> pd.DataFrame:
        """Return cached candles when available, otherwise fetch and populate."""
        key = self._key(symbol, interval, limit)
        try:
            cached = await self.cache.get(key)
        except Exception:
            logger.warning("cache get failed", extra={"key": key}, exc_info=True)
            cached = None
        if cached is not None:
            return candles_from_payload(cached)
        frame = await self.inner.get_ohlcv(symbol, interval, limit)
        try:
            await self.cache.set(key, candles_to_payload(frame), self.ttl)
        except Exception:
            logger.warning("cache set failed", extra={"key": key}, exc_info=True)
        return frame

    async def aclose(self) -> None:
        """Close the wrapped provider."""
        await self.inner.aclose()
