"""Simple rule-based trading signals derived from indicators.

These are illustrative heuristics, not trading advice:

* **RSI oversold / overbought** - RSI below / above configurable thresholds.
* **EMA cross** - the fast EMA crossed the slow EMA on the latest bar.
* **Bollinger breakout** - the latest close is outside the Bollinger Bands.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Literal

import pandas as pd

from market_pulse.indicators import core

Direction = Literal["bullish", "bearish"]


@dataclass(frozen=True, slots=True)
class SignalConfig:
    """Thresholds and periods used by :func:`generate_signals`."""

    rsi_period: int = 14
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0
    ema_fast: int = 9
    ema_slow: int = 21
    bb_period: int = 20
    bb_std: float = 2.0


@dataclass(frozen=True, slots=True)
class Signal:
    """A single signal fired on the latest bar."""

    name: str
    direction: Direction
    description: str
    value: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly dict."""
        return asdict(self)


def _last(series: pd.Series, offset: int = 1) -> float:
    if len(series) < offset:
        return math.nan
    return float(series.iloc[-offset])


def generate_signals(candles: pd.DataFrame, config: SignalConfig | None = None) -> list[Signal]:
    """Evaluate all signal rules on the latest bar of ``candles``."""
    cfg = config or SignalConfig()
    close = candles["close"].astype(float)
    signals: list[Signal] = []

    rsi_now = _last(core.rsi(close, cfg.rsi_period))
    if not math.isnan(rsi_now):
        if rsi_now < cfg.rsi_oversold:
            signals.append(
                Signal(
                    "rsi_oversold",
                    "bullish",
                    f"RSI({cfg.rsi_period}) {rsi_now:.1f} is below {cfg.rsi_oversold:g}",
                    rsi_now,
                )
            )
        elif rsi_now > cfg.rsi_overbought:
            signals.append(
                Signal(
                    "rsi_overbought",
                    "bearish",
                    f"RSI({cfg.rsi_period}) {rsi_now:.1f} is above {cfg.rsi_overbought:g}",
                    rsi_now,
                )
            )

    fast = core.ema(close, cfg.ema_fast)
    slow = core.ema(close, cfg.ema_slow)
    diff_now, diff_prev = _last(fast) - _last(slow), _last(fast, 2) - _last(slow, 2)
    if not (math.isnan(diff_now) or math.isnan(diff_prev)):
        label = f"EMA({cfg.ema_fast}) crossed EMA({cfg.ema_slow})"
        if diff_prev <= 0 < diff_now:
            signals.append(Signal("ema_cross_bullish", "bullish", f"{label} upward", diff_now))
        elif diff_prev >= 0 > diff_now:
            signals.append(Signal("ema_cross_bearish", "bearish", f"{label} downward", diff_now))

    bands = core.bollinger_bands(close, cfg.bb_period, cfg.bb_std)
    last_close = _last(close)
    upper, lower = _last(bands["upper"]), _last(bands["lower"])
    if not math.isnan(upper):
        if last_close > upper:
            signals.append(
                Signal("bollinger_breakout_up", "bullish", "Close above upper band", last_close)
            )
        elif last_close < lower:
            signals.append(
                Signal("bollinger_breakout_down", "bearish", "Close below lower band", last_close)
            )
    return signals


def summarize_bias(signals: list[Signal]) -> Literal["bullish", "bearish", "neutral"]:
    """Net direction of a signal list (simple vote)."""
    score = sum(1 if s.direction == "bullish" else -1 for s in signals)
    if score > 0:
        return "bullish"
    if score < 0:
        return "bearish"
    return "neutral"
