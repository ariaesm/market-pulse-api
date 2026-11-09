import math

import numpy as np
import pandas as pd
import pytest

from market_pulse.alerts import AlertEngine, AlertLimitError, AlertRule, AlertStore
from market_pulse.errors import (
    InvalidIndicatorError,
    NotFoundError,
    RuleSyntaxError,
    UnsupportedIntervalError,
)


def _candles(close: list[float]) -> pd.DataFrame:
    arr = np.asarray(close, dtype=float)
    return pd.DataFrame(
        {
            "open_time": pd.date_range("2025-01-01", periods=len(arr), freq="1h", tz="UTC"),
            "open": arr,
            "high": arr + 1,
            "low": arr - 1,
            "close": arr,
            "volume": np.full(len(arr), 10.0),
        }
    )


def test_create_validates_and_normalizes() -> None:
    rule = AlertRule.create("btcusdt", "1h", "RSI_14 < 30  and close > 1", name="dip")
    assert rule.symbol == "BTCUSDT"
    assert rule.expression == "rsi_14 < 30 and close > 1"
    assert len(rule.id) == 32
    with pytest.raises(RuleSyntaxError):
        AlertRule.create("BTCUSDT", "1h", "rsi_14 <")
    with pytest.raises(InvalidIndicatorError):
        AlertRule.create("BTCUSDT", "1h", "magic_7 > 1")
    with pytest.raises(UnsupportedIntervalError):
        AlertRule.create("BTCUSDT", "2h", "close > 1")


def test_store_crud_and_limit() -> None:
    store = AlertStore(max_rules=2)
    a = store.add(AlertRule.create("BTCUSDT", "1h", "close > 1"))
    store.add(AlertRule.create("ETHUSDT", "1h", "close > 1"))
    assert [r.id for r in store.list("btcusdt")] == [a.id]
    with pytest.raises(AlertLimitError):
        store.add(AlertRule.create("SOLUSDT", "1h", "close > 1"))
    assert store.delete(a.id) is a
    assert len(store) == 1
    with pytest.raises(NotFoundError):
        store.get(a.id)


def test_engine_fires_only_on_rising_edge() -> None:
    engine = AlertEngine()
    rule = AlertRule.create("BTCUSDT", "1h", "close > 100")
    below, above = _candles([90, 95, 99]), _candles([90, 95, 105])

    assert engine.evaluate(rule, below) is None
    event = engine.evaluate(rule, above)
    assert event is not None
    assert event.values == {"close": 105.0}
    assert event.bar_time == above["open_time"].iloc[-1].to_pydatetime()
    assert engine.evaluate(rule, above) is None  # still true: no duplicate
    assert engine.evaluate(rule, below) is None  # resets
    assert engine.evaluate(rule, above) is not None


def test_engine_uses_indicator_values_and_serializes() -> None:
    engine = AlertEngine()
    rule = AlertRule.create("BTCUSDT", "1h", "rsi_14 < 30", name="oversold")
    event = engine.evaluate(rule, _candles(list(np.linspace(200, 100, 40))))
    assert event is not None
    payload = event.to_dict()
    assert payload["type"] == "alert.triggered"
    assert payload["name"] == "oversold"
    assert payload["values"]["rsi_14"] < 30


def test_engine_handles_insufficient_history() -> None:
    engine = AlertEngine()
    rule = AlertRule.create("BTCUSDT", "1h", "rsi_14 < 30")
    assert engine.evaluate(rule, _candles([100, 99, 98])) is None
    assert math.isnan(engine.latest_values(rule, _candles([100, 99]))["rsi_14"])
    assert engine.evaluate(rule, _candles([]).iloc[0:0]) is None
