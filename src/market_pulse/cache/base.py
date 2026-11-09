"""Cache interface shared by the in-memory and Redis implementations."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Cache(Protocol):
    """Async key/value cache with per-entry TTL.

    Values must be JSON-serializable so that every backend can store them.
    """

    async def get(self, key: str) -> Any | None:
        """Return the cached value or ``None`` when missing/expired."""
        ...

    async def set(self, key: str, value: Any, ttl: float) -> None:
        """Store ``value`` for ``ttl`` seconds (``ttl <= 0`` disables caching)."""
        ...

    async def delete(self, key: str) -> None:
        """Remove ``key`` if present."""
        ...

    async def close(self) -> None:
        """Release backend resources."""
        ...
