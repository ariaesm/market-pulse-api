"""Market data provider interface and candle (de)serialization helpers.

Candles are exchanged as a ``pandas.DataFrame`` with a ``RangeIndex`` and the columns
:data:`CANDLE_COLUMNS`; ``open_time`` is a timezone-aware UTC timestamp.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from market_pulse.errors import UnsupportedIntervalError

CANDLE_COLUMNS: tuple[str, ...] = ("open_time", "open", "high", "low", "close", "volume")
SUPPORTED_INTERVALS: tuple[str, ...] = ("1m", "5m", "15m", "1h", "4h", "1d")


@dataclass(frozen=True, slots=True)
class SymbolInfo:
    """Metadata about a tradable symbol exposed by a provider."""

    symbol: str
    intervals: tuple[str, ...]
    base: str | None = None
    quote: str | None = None
    synthetic: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


def split_symbol(symbol: str) -> tuple[str | None, str | None]:
    """Best-effort split of ``BTCUSDT`` into ``("BTC", "USDT")``."""
    for quote in ("USDT", "USDC", "BUSD", "BTC", "ETH", "EUR", "USD"):
        if symbol.endswith(quote) and len(symbol) > len(quote):
            return symbol[: -len(quote)], quote
    return None, None


def validate_interval(interval: str, allowed: tuple[str, ...] = SUPPORTED_INTERVALS) -> str:
    """Return ``interval`` if allowed, else raise :class:`UnsupportedIntervalError`."""
    if interval not in allowed:
        raise UnsupportedIntervalError(
            f"interval {interval!r} is not supported", details={"supported": list(allowed)}
        )
    return interval


def normalize_candles(frame: pd.DataFrame) -> pd.DataFrame:
    """Coerce a raw frame into the canonical candle schema, sorted by ``open_time``."""
    missing = [c for c in CANDLE_COLUMNS if c not in frame.columns]
    if missing:
        raise ValueError(f"candle frame is missing columns: {missing}")
    out = frame.loc[:, list(CANDLE_COLUMNS)].copy()
    out["open_time"] = pd.to_datetime(out["open_time"], utc=True)
    for col in CANDLE_COLUMNS[1:]:
        out[col] = pd.to_numeric(out[col], errors="raise").astype(float)
    out = out.sort_values("open_time").drop_duplicates("open_time", keep="last")
    return out.reset_index(drop=True)


def candles_to_payload(frame: pd.DataFrame) -> dict[str, list[Any]]:
    """Serialize candles to a JSON-friendly column dict (``open_time`` as epoch ms)."""
    times = frame["open_time"].dt.tz_convert("UTC").dt.tz_localize(None)
    payload: dict[str, list[Any]] = {
        "open_time": (times.astype("datetime64[ms]").astype("int64")).tolist()
    }
    for col in CANDLE_COLUMNS[1:]:
        payload[col] = frame[col].astype(float).tolist()
    return payload


def candles_from_payload(payload: dict[str, list[Any]]) -> pd.DataFrame:
    """Inverse of :func:`candles_to_payload`."""
    frame = pd.DataFrame({col: payload[col] for col in CANDLE_COLUMNS})
    frame["open_time"] = pd.to_datetime(frame["open_time"], unit="ms", utc=True)
    return normalize_candles(frame)


class MarketDataProvider(ABC):
    """Abstract source of OHLCV candles.

    Implementations must be safe to call concurrently from the event loop.
    """

    #: Short identifier used in cache keys and logs.
    name: str = "provider"
    #: Whether the data served is synthetic (not real market data).
    synthetic: bool = False

    @abstractmethod
    async def list_symbols(self) -> list[SymbolInfo]:
        """Return the symbols this provider can serve."""

    @abstractmethod
    async def get_ohlcv(self, symbol: str, interval: str, limit: int) -> pd.DataFrame:
        """Return up to ``limit`` most recent candles in the canonical schema.

        Raises:
            SymbolNotFoundError: unknown symbol.
            UnsupportedIntervalError: interval not available.
            ProviderError: upstream failure.
        """

    async def aclose(self) -> None:  # noqa: B027 - optional hook, intentionally empty
        """Release resources (HTTP clients, file handles). Default: no-op."""
