"""In-process TTL cache with LRU eviction."""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any


class MemoryTTLCache:
    """A bounded, in-memory TTL cache.

    Entries expire ``ttl`` seconds after being set. When ``max_entries`` is reached the
    least recently used entry is evicted. The clock is injectable for deterministic tests.
    All operations are O(1) and run on the event loop thread, so no locking is required.
    """

    def __init__(
        self, max_entries: int = 1024, clock: Callable[[], float] = time.monotonic
    ) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        self.max_entries = max_entries
        self._clock = clock
        self._data: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def __len__(self) -> int:
        return len(self._data)

    async def get(self, key: str) -> Any | None:
        """Return a live entry and mark it as recently used."""
        item = self._data.get(key)
        if item is None:
            return None
        expires_at, value = item
        if expires_at <= self._clock():
            del self._data[key]
            return None
        self._data.move_to_end(key)
        return value

    async def set(self, key: str, value: Any, ttl: float) -> None:
        """Insert or replace an entry, evicting the LRU entry when full."""
        if ttl <= 0:
            self._data.pop(key, None)
            return
        self._data[key] = (self._clock() + ttl, value)
        self._data.move_to_end(key)
        while len(self._data) > self.max_entries:
            self._data.popitem(last=False)

    async def delete(self, key: str) -> None:
        """Remove an entry if present."""
        self._data.pop(key, None)

    async def close(self) -> None:
        """Drop all entries."""
        self._data.clear()
