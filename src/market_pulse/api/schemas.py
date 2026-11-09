"""Pydantic request/response models (also drive the OpenAPI schema)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Interval = Literal["1m", "5m", "15m", "1h", "4h", "1d"]
SYMBOL_PATTERN = r"^[A-Za-z0-9]{2,20}$"
DISCLAIMER = "Rule-based heuristics for educational purposes only. Not financial advice."


class ErrorBody(BaseModel):
    """Machine-readable error description."""

    code: str = Field(examples=["symbol_not_found"])
    message: str = Field(examples=["unknown symbol 'DOGEUSDT'"])
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """Envelope used by every error response."""

    error: ErrorBody


class HealthResponse(BaseModel):
    """Liveness and component status."""

    status: Literal["ok"] = "ok"
    version: str
    provider: str
    synthetic_data: bool
    cache_backend: str
    auth_enabled: bool
    alert_evaluator_running: bool
    alert_rules: int
    websocket_subscribers: int
    uptime_seconds: float


class SymbolOut(BaseModel):
    """A symbol available from the active provider."""

    symbol: str = Field(examples=["BTCUSDT"])
    base: str | None = Field(default=None, examples=["BTC"])
    quote: str | None = Field(default=None, examples=["USDT"])
    intervals: list[str] = Field(examples=[["1h", "1d"]])
    synthetic: bool = Field(description="True when the data is synthetic, not real prices.")


class SymbolsResponse(BaseModel):
    """List of symbols."""

    provider: str
    symbols: list[SymbolOut]


class CandleOut(BaseModel):
    """One OHLCV bar."""

    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class OHLCVResponse(BaseModel):
    """Candles for a symbol and interval, oldest first."""

    symbol: str
    interval: str
    provider: str
    synthetic: bool
    count: int
    candles: list[CandleOut]


class IndicatorsResponse(BaseModel):
    """Indicator values aligned to candles; warm-up values are ``null``."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "symbol": "BTCUSDT",
                    "interval": "1h",
                    "indicators": ["rsi_14", "ema_20"],
                    "columns": ["rsi_14", "ema_20"],
                    "count": 1,
                    "data": [
                        {
                            "open_time": "2025-02-11T15:00:00Z",
                            "close": 64012.5,
                            "rsi_14": 41.2,
                            "ema_20": 64250.9,
                        }
                    ],
                }
            ]
        }
    )

    symbol: str
    interval: str
    indicators: list[str]
    columns: list[str]
    count: int
    data: list[dict[str, Any]]


class SignalOut(BaseModel):
    """A signal firing on the latest bar."""

    name: str = Field(examples=["rsi_oversold"])
    direction: Literal["bullish", "bearish"]
    description: str
    value: float | None = None


class SignalsResponse(BaseModel):
    """Signals evaluated on the latest bar."""

    symbol: str
    interval: str
    as_of: datetime
    close: float
    bias: Literal["bullish", "bearish", "neutral"]
    signals: list[SignalOut]
    disclaimer: str = DISCLAIMER


class AlertCreate(BaseModel):
    """Request body for creating an alert rule."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "symbol": "BTCUSDT",
                    "interval": "1h",
                    "expression": "rsi_14 < 30 and close > 50000",
                    "name": "BTC oversold",
                }
            ]
        }
    )

    symbol: str = Field(pattern=SYMBOL_PATTERN)
    interval: Interval = "1h"
    expression: str = Field(
        min_length=3,
        max_length=256,
        description="`<indicator> <op> <number>` comparisons joined with and/or; "
        "parentheses allowed. Ops: < <= > >= == !=.",
    )
    name: str | None = Field(default=None, max_length=64)


class AlertOut(BaseModel):
    """A stored alert rule."""

    id: str
    symbol: str
    interval: str
    expression: str
    name: str | None
    identifiers: list[str]
    created_at: datetime


class AlertListResponse(BaseModel):
    """All alert rules (optionally filtered)."""

    count: int
    alerts: list[AlertOut]
