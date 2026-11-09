"""Caching layer: a small async interface with memory and Redis backends."""

from __future__ import annotations

from market_pulse.cache.base import Cache
from market_pulse.cache.memory import MemoryTTLCache
from market_pulse.config import Settings

__all__ = ["Cache", "MemoryTTLCache", "build_cache"]


def build_cache(settings: Settings) -> Cache:
    """Instantiate the cache backend selected by ``settings.cache_backend``."""
    if settings.cache_backend == "redis":
        from market_pulse.cache.redis_cache import RedisCache

        return RedisCache(settings.redis_url)
    return MemoryTTLCache(max_entries=settings.cache_max_entries)
