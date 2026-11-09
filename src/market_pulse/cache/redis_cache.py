"""Redis-backed cache using ``redis.asyncio`` (optional dependency)."""

from __future__ import annotations

import json
from typing import Any


class RedisCache:
    """JSON-serializing cache on top of Redis.

    ``redis`` is imported lazily so the package does not require it unless this backend
    is selected (``MP_CACHE_BACKEND=redis``). A pre-built client can be injected.
    """

    def __init__(
        self, url: str = "redis://localhost:6379/0", *, client: Any = None, prefix: str = "mp:"
    ) -> None:
        if client is None:
            from redis import asyncio as redis_asyncio

            client = redis_asyncio.from_url(url)
        self._client = client
        self.prefix = prefix

    def _key(self, key: str) -> str:
        return f"{self.prefix}{key}"

    async def get(self, key: str) -> Any | None:
        """Fetch and JSON-decode a value."""
        raw = await self._client.get(self._key(key))
        if raw is None:
            return None
        return json.loads(raw)

    async def set(self, key: str, value: Any, ttl: float) -> None:
        """JSON-encode and store a value with a millisecond-precision TTL."""
        if ttl <= 0:
            await self.delete(key)
            return
        await self._client.set(self._key(key), json.dumps(value), px=max(1, int(ttl * 1000)))

    async def delete(self, key: str) -> None:
        """Delete a key."""
        await self._client.delete(self._key(key))

    async def ping(self) -> bool:
        """Return ``True`` when Redis answers a PING."""
        return bool(await self._client.ping())

    async def close(self) -> None:
        """Close the connection pool."""
        await self._client.aclose()
