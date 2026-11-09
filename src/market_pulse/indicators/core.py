"""Technical indicators implemented from scratch with numpy/pandas.

All functions are pure: they take ``pandas.Series`` inputs and return new Series (or a
DataFrame for multi-output indicators) aligned to the input index. Warm-up periods are
filled with ``NaN``.

Conventions
-----------
* **EMA** uses ``alpha = 2 / (period + 1)`` and is seeded with the SMA of the first
  ``period`` valid values (the classic charting convention), so the first value appears
  at position ``period - 1`` after any leading ``NaN``.
* **RSI** and **ATR** use Wilder's smoothing: the first average is a simple mean, then
  ``avg_t = (avg_{t-1} * (period - 1) + x_t) / period``.
* **Bollinger Bands** use the population standard deviation (``ddof=0``).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = [
    "atr",
    "bollinger_bands",
    "ema",
    "macd",
    "rsi",
    "sma",
    "stochastic",
    "true_range",
]


def _check_period(period: int) -> None:
    if not isinstance(period, int) or period < 1:
        raise ValueError(f"period must be a positive integer, got {period!r}")


def _ema_values(values: np.ndarray, period: int) -> np.ndarray:
    """EMA over a float array, skipping leading NaNs and seeding with an SMA."""
    out = np.full(values.shape, np.nan, dtype=float)
    valid = np.flatnonzero(~np.isnan(values))
    if valid.size == 0:
        return out
    start = int(valid[0])
    seed_end = start + period
    if seed_end > values.size:
        return out
    alpha = 2.0 / (period + 1.0)
    prev = float(np.mean(values[start:seed_end]))
    out[seed_end - 1] = prev
    for i in range(seed_end, values.size):
        prev = alpha * values[i] + (1.0 - alpha) * prev
        out[i] = prev
    return out


def _wilder_values(values: np.ndarray, period: int, start: int) -> np.ndarray:
    """Wilder smoothing; the seed is the mean of ``values[start:start + period]``."""
    out = np.full(values.shape, np.nan, dtype=float)
    seed_end = start + period
    if seed_end > values.size:
        return out
    prev = float(np.mean(values[start:seed_end]))
    out[seed_end - 1] = prev
    for i in range(seed_end, values.size):
        prev = (prev * (period - 1) + values[i]) / period
        out[i] = prev
    return out


def sma(series: pd.Series, period: int) -> pd.Series:
    """Simple moving average."""
    _check_period(period)
    return series.astype(float).rolling(window=period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential moving average seeded with the SMA of the first ``period`` values."""
    _check_period(period)
    values = series.to_numpy(dtype=float)
    return pd.Series(_ema_values(values, period), index=series.index, name=series.name)


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index using Wilder's smoothing.

    The first value is produced at position ``period`` (``period`` price changes are
    needed). When the average loss is zero the RSI is 100 (or 50 if there was no
    movement at all).
    """
    _check_period(period)
    values = close.to_numpy(dtype=float)
    out = np.full(values.shape, np.nan, dtype=float)
    if values.size <= period:
        return pd.Series(out, index=close.index)
    delta = np.diff(values)
    gains = np.clip(delta, 0.0, None)
    losses = np.clip(-delta, 0.0, None)
    avg_gain = _wilder_values(gains, period, 0)
    avg_loss = _wilder_values(losses, period, 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = avg_gain / avg_loss
        rsi_values = 100.0 - 100.0 / (1.0 + rs)
    rsi_values = np.where((avg_loss == 0) & (avg_gain > 0), 100.0, rsi_values)
    rsi_values = np.where((avg_loss == 0) & (avg_gain == 0), 50.0, rsi_values)
    rsi_values = np.where(np.isnan(avg_gain), np.nan, rsi_values)
    out[1:] = rsi_values
    return pd.Series(out, index=close.index)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """Moving Average Convergence Divergence.

    Returns a DataFrame with ``macd`` (fast EMA - slow EMA), ``signal`` (EMA of the
    MACD line) and ``hist`` (macd - signal).
    """
    for p in (fast, slow, signal):
        _check_period(p)
    if fast >= slow:
        raise ValueError("fast period must be smaller than slow period")
    line = ema(close, fast) - ema(close, slow)
    signal_line = pd.Series(_ema_values(line.to_numpy(dtype=float), signal), index=close.index)
    return pd.DataFrame({"macd": line, "signal": signal_line, "hist": line - signal_line})


def bollinger_bands(close: pd.Series, period: int = 20, num_std: float = 2.0) -> pd.DataFrame:
    """Bollinger Bands: SMA middle band +/- ``num_std`` population standard deviations."""
    _check_period(period)
    middle = sma(close, period)
    std = close.astype(float).rolling(window=period, min_periods=period).std(ddof=0)
    return pd.DataFrame(
        {"upper": middle + num_std * std, "middle": middle, "lower": middle - num_std * std}
    )


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """True range; the first bar (no previous close) uses ``high - low``."""
    prev_close = close.astype(float).shift(1)
    ranges = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1)
    return ranges.max(axis=1, skipna=True).astype(float)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average True Range with Wilder's smoothing.

    The seed is the mean of the first ``period`` true ranges, so the first value is at
    position ``period - 1``.
    """
    _check_period(period)
    tr = true_range(high, low, close).to_numpy(dtype=float)
    return pd.Series(_wilder_values(tr, period, 0), index=close.index)


def stochastic(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
    smooth_d: int = 3,
) -> pd.DataFrame:
    """Stochastic oscillator (fast %K and its SMA %D).

    ``%K = 100 * (close - lowest_low) / (highest_high - lowest_low)`` over ``period``
    bars. A flat window (zero range) yields 50.
    """
    _check_period(period)
    _check_period(smooth_d)
    lowest = low.astype(float).rolling(window=period, min_periods=period).min()
    highest = high.astype(float).rolling(window=period, min_periods=period).max()
    span = highest - lowest
    k = 100.0 * (close.astype(float) - lowest) / span.replace(0.0, np.nan)
    k = k.where(~((span == 0) & lowest.notna()), 50.0)
    d = k.rolling(window=smooth_d, min_periods=smooth_d).mean()
    return pd.DataFrame({"k": k, "d": d})
