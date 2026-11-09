"""Provider backed by Binance's public klines REST endpoint (no API key required).

``httpx`` is imported lazily so that the parsing logic in this module stays importable
and testable without it. Any object exposing ``async get(url, params=...)`` returning a
response with ``status_code`` and ``json()`` can be injected as ``client``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

import pandas as pd

from market_pulse.errors import AppError, ProviderError, SymbolNotFoundError
from market_pulse.providers.base import (
    SUPPORTED_INTERVALS,
    MarketDataProvider,
    SymbolInfo,
    normalize_candles,
    split_symbol,
    validate_interval,
)

BINANCE_MAX_LIMIT = 1000
_INVALID_SYMBOL_CODE = -1121


class _Response(Protocol):
    status_code: int

    def json(self) -> Any: ...


class AsyncHTTPClient(Protocol):
    """Minimal async HTTP client interface (satisfied by ``httpx.AsyncClient``)."""

    async def get(self, url: str, *, params: dict[str, Any] | None = None) -> _Response: ...


def parse_klines(rows: Sequence[Sequence[Any]]) -> pd.DataFrame:
    """Convert Binance kline arrays into the canonical candle frame.

    Each row is ``[open_time_ms, open, high, low, close, volume, close_time, ...]`` with
    prices encoded as strings.
    """
    if not rows:
        return normalize_candles(
            pd.DataFrame(columns=["open_time", "open", "high", "low", "close", "volume"])
        )
    try:
        frame = pd.DataFrame(
            [row[:6] for row in rows],
            columns=["open_time", "open", "high", "low", "close", "volume"],
        )
        frame["open_time"] = pd.to_datetime(frame["open_time"].astype("int64"), unit="ms", utc=True)
        return normalize_candles(frame)
    except (ValueError, TypeError, IndexError) as exc:
        raise ProviderError(f"malformed kline payload: {exc}") from exc


class BinanceProvider(MarketDataProvider):
    """Fetch klines from ``GET /api/v3/klines``."""

    name = "binance"
    synthetic = False

    def __init__(
        self,
        base_url: str = "https://api.binance.com",
        symbols: Sequence[str] = ("BTCUSDT", "ETHUSDT"),
        *,
        timeout: float = 10.0,
        client: AsyncHTTPClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.symbols = tuple(s.upper() for s in symbols)
        self.timeout = timeout
        self._client = client
        self._owns_client = client is None

    def _get_client(self) -> AsyncHTTPClient:
        if self._client is None:
            import httpx

            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout)
        return self._client

    async def list_symbols(self) -> list[SymbolInfo]:
        """Return the configured symbol allow-list."""
        return [SymbolInfo(s, SUPPORTED_INTERVALS, *split_symbol(s)) for s in self.symbols]

    async def get_ohlcv(self, symbol: str, interval: str, limit: int) -> pd.DataFrame:
        """Fetch the most recent ``limit`` klines for ``symbol``."""
        symbol = symbol.upper()
        validate_interval(interval)
        if self.symbols and symbol not in self.symbols:
            raise SymbolNotFoundError(
                f"unknown symbol {symbol!r}", details={"available": list(self.symbols)}
            )
        params = {"symbol": symbol, "interval": interval, "limit": min(limit, BINANCE_MAX_LIMIT)}
        try:
            response = await self._get_client().get(f"{self.base_url}/api/v3/klines", params=params)
        except AppError:
            raise
        except Exception as exc:  # network errors from whatever client is injected
            raise ProviderError(f"binance request failed: {exc}") from exc
        if response.status_code != 200:
            body = _safe_json(response)
            if isinstance(body, dict) and body.get("code") == _INVALID_SYMBOL_CODE:
                raise SymbolNotFoundError(f"unknown symbol {symbol!r}")
            raise ProviderError(
                f"binance returned HTTP {response.status_code}", details={"body": body}
            )
        return parse_klines(response.json())

    async def aclose(self) -> None:
        """Close the HTTP client if this provider created it."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()  # type: ignore[attr-defined]
            self._client = None


def _safe_json(response: _Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None
