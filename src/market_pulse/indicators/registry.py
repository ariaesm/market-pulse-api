"""Indicator specifications: parse names like ``rsi``, ``ema_20`` or ``bbands_20``.

A *spec* is what clients request (``?names=rsi,ema_20,macd``). Each spec produces one
or more named *columns* (``rsi_14``, ``ema_20``, ``macd``/``macd_signal``/``macd_hist``),
which are also the identifiers usable in alert rules.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass

import pandas as pd

from market_pulse.errors import InvalidIndicatorError
from market_pulse.indicators import core

PRICE_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "volume")

#: Default period per indicator family; ``None`` means the family takes no period.
DEFAULT_PERIODS: dict[str, int | None] = {
    "sma": 20,
    "ema": 20,
    "rsi": 14,
    "atr": 14,
    "bbands": 20,
    "stoch": 14,
    "macd": None,
}

MAX_PERIOD = 500

_SPEC_RE = re.compile(r"^(?P<name>[a-z]+)(?:_(?P<period>\d+))?$")
_COLUMN_PATTERNS: tuple[tuple[re.Pattern[str], Callable[[re.Match[str]], str]], ...] = (
    (re.compile(r"^(sma|ema|rsi|atr)_(\d+)$"), lambda m: f"{m[1]}_{m[2]}"),
    (re.compile(r"^macd(?:_signal|_hist)?$"), lambda m: "macd"),
    (re.compile(r"^bb_(?:upper|middle|lower)_(\d+)$"), lambda m: f"bbands_{m[1]}"),
    (re.compile(r"^stoch_[kd]_(\d+)$"), lambda m: f"stoch_{m[1]}"),
)


@dataclass(frozen=True, slots=True)
class IndicatorSpec:
    """A parsed indicator request, e.g. ``IndicatorSpec("ema", 20)``."""

    name: str
    period: int | None

    @property
    def key(self) -> str:
        """Canonical spec string (``rsi`` -> ``rsi_14``)."""
        return self.name if self.period is None else f"{self.name}_{self.period}"

    @property
    def columns(self) -> tuple[str, ...]:
        """Output column names produced by this spec."""
        p = self.period
        match self.name:
            case "macd":
                return ("macd", "macd_signal", "macd_hist")
            case "bbands":
                return (f"bb_upper_{p}", f"bb_middle_{p}", f"bb_lower_{p}")
            case "stoch":
                return (f"stoch_k_{p}", f"stoch_d_{p}")
            case _:
                return (f"{self.name}_{p}",)

    def compute(self, candles: pd.DataFrame) -> pd.DataFrame:
        """Compute this indicator on an OHLCV DataFrame, returning its output columns."""
        close, high, low = candles["close"], candles["high"], candles["low"]
        p = self.period if self.period is not None else 0
        match self.name:
            case "sma":
                data = {self.columns[0]: core.sma(close, p)}
            case "ema":
                data = {self.columns[0]: core.ema(close, p)}
            case "rsi":
                data = {self.columns[0]: core.rsi(close, p)}
            case "atr":
                data = {self.columns[0]: core.atr(high, low, close, p)}
            case "macd":
                frame = core.macd(close)
                data = dict(
                    zip(self.columns, (frame["macd"], frame["signal"], frame["hist"]), strict=True)
                )
            case "bbands":
                frame = core.bollinger_bands(close, p)
                data = dict(
                    zip(
                        self.columns, (frame["upper"], frame["middle"], frame["lower"]), strict=True
                    )
                )
            case "stoch":
                frame = core.stochastic(high, low, close, p)
                data = dict(zip(self.columns, (frame["k"], frame["d"]), strict=True))
            case _:  # pragma: no cover - guarded by parse_spec
                raise InvalidIndicatorError(f"unknown indicator {self.name!r}")
        return pd.DataFrame(data, index=candles.index)


def parse_spec(raw: str) -> IndicatorSpec:
    """Parse a single indicator spec such as ``rsi``, ``rsi_7`` or ``macd``."""
    text = raw.strip().lower()
    match = _SPEC_RE.match(text)
    if not match or match["name"] not in DEFAULT_PERIODS:
        raise InvalidIndicatorError(
            f"unknown indicator {raw!r}",
            details={"supported": sorted(DEFAULT_PERIODS)},
        )
    name = match["name"]
    default = DEFAULT_PERIODS[name]
    if default is None:
        if match["period"] is not None:
            raise InvalidIndicatorError(f"indicator {name!r} does not take a period")
        return IndicatorSpec(name, None)
    period = int(match["period"]) if match["period"] is not None else default
    if not 1 <= period <= MAX_PERIOD:
        raise InvalidIndicatorError(
            f"period for {name!r} must be between 1 and {MAX_PERIOD}", details={"period": period}
        )
    if name == "stoch" and period < 2:
        raise InvalidIndicatorError("stoch period must be at least 2")
    return IndicatorSpec(name, period)


def parse_specs(raw: str | Iterable[str]) -> list[IndicatorSpec]:
    """Parse a comma-separated list (or iterable) of specs, de-duplicated in order."""
    items = raw.split(",") if isinstance(raw, str) else list(raw)
    specs: dict[str, IndicatorSpec] = {}
    for item in items:
        if not item.strip():
            continue
        spec = parse_spec(item)
        specs.setdefault(spec.key, spec)
    if not specs:
        raise InvalidIndicatorError("at least one indicator name is required")
    return list(specs.values())


def spec_for_column(column: str) -> IndicatorSpec | None:
    """Return the spec that produces ``column`` (``None`` for raw price columns).

    Raises :class:`InvalidIndicatorError` for unknown identifiers.
    """
    if column in PRICE_COLUMNS:
        return None
    for pattern, to_spec in _COLUMN_PATTERNS:
        match = pattern.match(column)
        if match:
            return parse_spec(to_spec(match))
    raise InvalidIndicatorError(
        f"unknown indicator column {column!r}",
        details={"examples": ["rsi_14", "ema_20", "macd_hist", "bb_upper_20", "close"]},
    )


def compute_indicators(candles: pd.DataFrame, specs: Iterable[IndicatorSpec]) -> pd.DataFrame:
    """Compute several specs and concatenate their columns (index-aligned to ``candles``)."""
    frames = [spec.compute(candles) for spec in specs]
    if not frames:
        return pd.DataFrame(index=candles.index)
    return pd.concat(frames, axis=1)


def compute_columns(candles: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    """Compute exactly the requested columns (indicator or price) for ``candles``."""
    wanted = list(dict.fromkeys(columns))
    specs: dict[str, IndicatorSpec] = {}
    for column in wanted:
        spec = spec_for_column(column)
        if spec is not None:
            specs.setdefault(spec.key, spec)
    computed = compute_indicators(candles, specs.values())
    for column in wanted:
        if column in PRICE_COLUMNS:
            computed[column] = candles[column].astype(float)
    return computed[wanted]
