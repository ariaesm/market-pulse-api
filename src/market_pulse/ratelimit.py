"""In-memory token-bucket rate limiting."""

from __future__ import annotations

import math
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(slots=True)
class TokenBucket:
    """Classic token bucket: ``capacity`` tokens, refilled at ``rate`` tokens/second."""

    capacity: float
    rate: float
    tokens: float
    updated: float

    def consume(self, now: float, cost: float = 1.0) -> tuple[bool, float]:
        """Try to take ``cost`` tokens.

        Returns ``(allowed, retry_after_seconds)``; ``retry_after`` is 0 when allowed.
        """
        elapsed = max(0.0, now - self.updated)
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.updated = now
        if self.tokens >= cost:
            self.tokens -= cost
            return True, 0.0
        return False, (cost - self.tokens) / self.rate


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    """Outcome of a rate-limit check, including values for response headers."""

    allowed: bool
    limit: int
    remaining: int
    retry_after: float

    @property
    def retry_after_header(self) -> str:
        """Whole seconds to wait, rounded up (``Retry-After`` header value)."""
        return str(max(1, math.ceil(self.retry_after)))


class RateLimiter:
    """Per-key token buckets with a bounded number of tracked keys.

    ``per_minute`` sets the sustained rate and ``burst`` the bucket capacity. Keys are
    evicted least-recently-used once ``max_keys`` is exceeded. Single-process only: run
    behind a shared limiter (e.g. at the proxy or in Redis) when scaling horizontally.
    """

    def __init__(
        self,
        per_minute: int,
        burst: int,
        *,
        max_keys: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if per_minute < 1 or burst < 1:
            raise ValueError("per_minute and burst must be >= 1")
        self.per_minute = per_minute
        self.burst = burst
        self.rate = per_minute / 60.0
        self.max_keys = max_keys
        self._clock = clock
        self._buckets: OrderedDict[str, TokenBucket] = OrderedDict()

    def check(self, key: str, cost: float = 1.0) -> RateLimitDecision:
        """Consume a token for ``key`` and report whether the request may proceed."""
        now = self._clock()
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = TokenBucket(self.burst, self.rate, float(self.burst), now)
            self._buckets[key] = bucket
            while len(self._buckets) > self.max_keys:
                self._buckets.popitem(last=False)
        else:
            self._buckets.move_to_end(key)
        allowed, retry_after = bucket.consume(now, cost)
        return RateLimitDecision(allowed, self.burst, int(bucket.tokens), retry_after)
