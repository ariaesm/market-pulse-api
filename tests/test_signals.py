import numpy as np
import pandas as pd

from market_pulse.signals import Signal, SignalConfig, generate_signals, summarize_bias


def _candles(close: list[float] | np.ndarray) -> pd.DataFrame:
    close = np.asarray(close, dtype=float)
    return pd.DataFrame(
        {
            "open_time": pd.date_range("2025-01-01", periods=len(close), freq="1h", tz="UTC"),
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.ones(len(close)),
        }
    )


def _names(signals: list[Signal]) -> set[str]:
    return {s.name for s in signals}


def test_rsi_oversold_and_overbought() -> None:
    falling = generate_signals(_candles(np.linspace(200, 100, 60)))
    rising = generate_signals(_candles(np.linspace(100, 200, 60)))
    assert "rsi_oversold" in _names(falling)
    assert "rsi_overbought" in _names(rising)
    assert summarize_bias(rising) == "bearish"


def test_ema_cross_fires_exactly_once_on_v_shape() -> None:
    # Fall for 40 bars, then rise: the fast EMA crosses above the slow EMA once.
    series = np.concatenate([np.linspace(200, 100, 40), np.linspace(101, 160, 40)])
    hits = [
        n
        for n in range(30, len(series) + 1)
        if "ema_cross_bullish" in _names(generate_signals(_candles(series[:n])))
    ]
    assert len(hits) == 1
    assert hits[0] > 40


def test_bollinger_breakout_on_spike() -> None:
    flat = [100.0] * 30
    up = generate_signals(_candles([*flat, 110.0]))
    down = generate_signals(_candles([*flat, 90.0]))
    assert "bollinger_breakout_up" in _names(up)
    assert "bollinger_breakout_down" in _names(down)


def test_no_signals_on_short_history_and_custom_config() -> None:
    assert generate_signals(_candles([1.0, 2.0, 3.0])) == []
    cfg = SignalConfig(rsi_oversold=5.0, rsi_overbought=95.0)
    names = _names(generate_signals(_candles(np.linspace(100, 101, 60) + np.sin(range(60))), cfg))
    assert not names & {"rsi_oversold", "rsi_overbought"}


def test_summarize_bias() -> None:
    bull = Signal("a", "bullish", "")
    bear = Signal("b", "bearish", "")
    assert summarize_bias([bull, bull, bear]) == "bullish"
    assert summarize_bias([bull, bear]) == "neutral"
    assert summarize_bias([bear]) == "bearish"
