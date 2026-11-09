import asyncio
from typing import Any

import pandas as pd

from market_pulse.cache import Cache, MemoryTTLCache, build_cache
from market_pulse.cache.redis_cache import RedisCache
from market_pulse.config import Settings
from market_pulse.providers.base import MarketDataProvider, SymbolInfo
from market_pulse.providers.binance import parse_klines
from market_pulse.providers.cached import CachedProvider


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_memory_cache_expires_entries() -> None:
    clock = FakeClock()
    cache = MemoryTTLCache(clock=clock)

    async def scenario() -> None:
        await cache.set("a", {"x": 1}, ttl=10)
        assert await cache.get("a") == {"x": 1}
        clock.now += 9.9
        assert await cache.get("a") == {"x": 1}
        clock.now += 0.2
        assert await cache.get("a") is None
        assert len(cache) == 0

    asyncio.run(scenario())


def test_memory_cache_evicts_least_recently_used() -> None:
    cache = MemoryTTLCache(max_entries=2)

    async def scenario() -> None:
        await cache.set("a", 1, 60)
        await cache.set("b", 2, 60)
        await cache.get("a")  # "b" is now least recently used
        await cache.set("c", 3, 60)
        assert await cache.get("b") is None
        assert await cache.get("a") == 1
        assert await cache.get("c") == 3
        await cache.set("a", 1, 0)  # non-positive TTL removes
        assert await cache.get("a") is None

    asyncio.run(scenario())


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key: str) -> bytes | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, px: int) -> None:
        self.store[key] = value.encode()
        self.ttls[key] = px

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        self.store.clear()


def test_redis_cache_serializes_json_with_prefix_and_ttl() -> None:
    fake = FakeRedis()
    cache = RedisCache(client=fake)

    async def scenario() -> None:
        await cache.set("k", {"values": [1.5, 2]}, ttl=2.5)
        assert fake.store["mp:k"] == b'{"values": [1.5, 2]}'
        assert fake.ttls["mp:k"] == 2500
        assert await cache.get("k") == {"values": [1.5, 2]}
        assert await cache.ping() is True
        await cache.delete("k")
        assert await cache.get("k") is None

    asyncio.run(scenario())
    assert isinstance(cache, Cache)


def test_build_cache_defaults_to_memory() -> None:
    assert isinstance(build_cache(Settings()), MemoryTTLCache)


class CountingProvider(MarketDataProvider):
    name = "counting"

    def __init__(self) -> None:
        self.calls = 0

    async def list_symbols(self) -> list[SymbolInfo]:
        return []

    async def get_ohlcv(self, symbol: str, interval: str, limit: int) -> pd.DataFrame:
        self.calls += 1
        return parse_klines([[1735689600000, "1", "2", "0.5", "1.5", "10"]])


class BrokenCache:
    async def get(self, key: str) -> Any | None:
        raise ConnectionError("cache down")

    async def set(self, key: str, value: Any, ttl: float) -> None:
        raise ConnectionError("cache down")

    async def delete(self, key: str) -> None:
        return None

    async def close(self) -> None:
        return None


def test_cached_provider_reads_through_and_survives_cache_failures() -> None:
    inner = CountingProvider()
    provider = CachedProvider(inner, MemoryTTLCache(), ttl=60)

    async def scenario() -> None:
        first = await provider.get_ohlcv("btcusdt", "1h", 1)
        second = await provider.get_ohlcv("BTCUSDT", "1h", 1)
        pd.testing.assert_frame_equal(first, second)
        assert inner.calls == 1

        broken = CachedProvider(inner, BrokenCache(), ttl=60)
        frame = await broken.get_ohlcv("BTCUSDT", "1h", 1)
        assert len(frame) == 1
        assert inner.calls == 2

    asyncio.run(scenario())
