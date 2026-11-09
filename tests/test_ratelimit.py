import asyncio
import json
from typing import Any

import pytest

from market_pulse.ratelimit import RateLimiter, TokenBucket


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_token_bucket_refills_over_time() -> None:
    bucket = TokenBucket(capacity=2, rate=1.0, tokens=2, updated=0.0)
    assert bucket.consume(0.0) == (True, 0.0)
    assert bucket.consume(0.0) == (True, 0.0)
    allowed, retry = bucket.consume(0.0)
    assert not allowed
    assert retry == pytest.approx(1.0)
    assert bucket.consume(0.5)[0] is False
    assert bucket.consume(1.0)[0] is True
    bucket.consume(100.0)
    assert bucket.tokens == pytest.approx(1.0)  # capped at capacity, minus one


def test_rate_limiter_burst_then_sustained_rate() -> None:
    clock = FakeClock()
    limiter = RateLimiter(per_minute=60, burst=3, clock=clock)
    decisions = [limiter.check("a") for _ in range(4)]
    assert [d.allowed for d in decisions] == [True, True, True, False]
    assert decisions[0].remaining == 2
    assert decisions[-1].retry_after_header == "1"
    assert limiter.check("b").allowed  # keys are independent
    clock.now += 1.0
    assert limiter.check("a").allowed


def test_rate_limiter_evicts_old_keys() -> None:
    limiter = RateLimiter(per_minute=1, burst=1, max_keys=2, clock=FakeClock())
    limiter.check("a")
    limiter.check("b")
    limiter.check("c")  # evicts "a", which then gets a fresh bucket
    assert limiter.check("a").allowed


# --- ASGI middleware (needs only Starlette) ---------------------------------

starlette = pytest.importorskip("starlette")


async def _ok_app(scope: dict[str, Any], receive: Any, send: Any) -> None:
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


def _call(app: Any, path: str = "/v1/symbols", headers: list[tuple[bytes, bytes]] | None = None):
    messages: list[dict[str, Any]] = []
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": headers or [],
        "client": ("10.0.0.1", 1234),
    }

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    asyncio.run(app(scope, receive, send))
    start = messages[0]
    hdrs = {k.decode().lower(): v.decode() for k, v in start["headers"]}
    body = b"".join(m.get("body", b"") for m in messages[1:])
    return start["status"], hdrs, body


def test_rate_limit_middleware_returns_429_envelope() -> None:
    from market_pulse.api.middleware import RateLimitMiddleware

    app = RateLimitMiddleware(_ok_app, RateLimiter(per_minute=1, burst=1, clock=FakeClock()))
    status, headers, _ = _call(app)
    assert status == 200
    assert headers["x-ratelimit-remaining"] == "0"
    status, headers, body = _call(app)
    assert status == 429
    assert headers["retry-after"] == "60"
    assert json.loads(body)["error"]["code"] == "rate_limited"
    assert _call(app, path="/health")[0] == 200  # exempt
    assert _call(app, headers=[(b"x-api-key", b"k1")])[0] == 200  # separate bucket


def test_request_context_middleware_sets_request_id() -> None:
    from market_pulse.api.middleware import RequestContextMiddleware

    app = RequestContextMiddleware(_ok_app)
    _, headers, _ = _call(app, headers=[(b"x-request-id", b"abc123")])
    assert headers["x-request-id"] == "abc123"
    _, headers, _ = _call(app)
    assert len(headers["x-request-id"]) == 32
