"""In-process publish/subscribe broker for alert events (WebSocket fan-out)."""

from __future__ import annotations

import asyncio
from typing import Any


class Subscription:
    """A subscriber's bounded queue. Slow consumers lose the oldest events first."""

    def __init__(self, maxsize: int = 100, symbol: str | None = None) -> None:
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=maxsize)
        self.symbol = symbol.upper() if symbol else None
        self.dropped = 0

    def matches(self, event: dict[str, Any]) -> bool:
        """Whether this subscriber wants ``event`` (symbol filter)."""
        return self.symbol is None or event.get("symbol") == self.symbol

    def offer(self, event: dict[str, Any]) -> None:
        """Enqueue without blocking, dropping the oldest event when full."""
        if self.queue.full():
            self.queue.get_nowait()
            self.dropped += 1
        self.queue.put_nowait(event)

    async def get(self) -> dict[str, Any]:
        """Wait for the next event."""
        return await self.queue.get()


class AlertBroker:
    """Fan out events to all current subscribers.

    Must be used from a single event loop. For multi-process deployments, replace with a
    shared channel such as Redis pub/sub.
    """

    def __init__(self, queue_size: int = 100) -> None:
        self.queue_size = queue_size
        self._subscribers: set[Subscription] = set()

    @property
    def subscriber_count(self) -> int:
        """Number of active subscribers."""
        return len(self._subscribers)

    def subscribe(self, symbol: str | None = None) -> Subscription:
        """Register a new subscriber, optionally filtered to one symbol."""
        sub = Subscription(self.queue_size, symbol)
        self._subscribers.add(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        """Remove a subscriber (idempotent)."""
        self._subscribers.discard(sub)

    def publish(self, event: dict[str, Any]) -> int:
        """Deliver ``event`` to matching subscribers; returns how many received it."""
        delivered = 0
        for sub in list(self._subscribers):
            if sub.matches(event):
                sub.offer(event)
                delivered += 1
        return delivered
