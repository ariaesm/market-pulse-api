import numpy as np
import pandas as pd
import pytest

from market_pulse.errors import InvalidIndicatorError
from market_pulse.indicators import (
    IndicatorSpec,
    compute_columns,
    compute_indicators,
    parse_spec,
    parse_specs,
    spec_for_column,
)


@pytest.fixture
def candles() -> pd.DataFrame:
    rng = np.random.default_rng(1)
    close = 100 + rng.normal(0, 1, 120).cumsum()
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": rng.uniform(1, 10, 120),
        }
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("rsi", IndicatorSpec("rsi", 14)),
        ("RSI_7", IndicatorSpec("rsi", 7)),
        ("ema_20", IndicatorSpec("ema", 20)),
        (" macd ", IndicatorSpec("macd", None)),
        ("bbands", IndicatorSpec("bbands", 20)),
        ("atr", IndicatorSpec("atr", 14)),
        ("stoch_5", IndicatorSpec("stoch", 5)),
    ],
)
def test_parse_spec(raw: str, expected: IndicatorSpec) -> None:
    assert parse_spec(raw) == expected


@pytest.mark.parametrize("raw", ["foo", "rsi_0", "macd_9", "ema_x", "rsi_9999", ""])
def test_parse_spec_rejects_invalid(raw: str) -> None:
    with pytest.raises(InvalidIndicatorError):
        parse_spec(raw)


def test_parse_specs_deduplicates() -> None:
    specs = parse_specs("rsi,rsi_14,ema_20,,macd")
    assert [s.key for s in specs] == ["rsi_14", "ema_20", "macd"]


def test_spec_columns() -> None:
    assert parse_spec("bbands").columns == ("bb_upper_20", "bb_middle_20", "bb_lower_20")
    assert parse_spec("macd").columns == ("macd", "macd_signal", "macd_hist")
    assert parse_spec("stoch").columns == ("stoch_k_14", "stoch_d_14")


def test_spec_for_column_roundtrip() -> None:
    assert spec_for_column("close") is None
    assert spec_for_column("macd_hist") == IndicatorSpec("macd", None)
    assert spec_for_column("bb_lower_10") == IndicatorSpec("bbands", 10)
    assert spec_for_column("stoch_d_14") == IndicatorSpec("stoch", 14)
    with pytest.raises(InvalidIndicatorError):
        spec_for_column("price")


def test_compute_indicators_columns_and_alignment(candles: pd.DataFrame) -> None:
    result = compute_indicators(candles, parse_specs("rsi,ema_20,macd,bbands,atr,stoch"))
    assert list(result.columns) == [
        "rsi_14",
        "ema_20",
        "macd",
        "macd_signal",
        "macd_hist",
        "bb_upper_20",
        "bb_middle_20",
        "bb_lower_20",
        "atr_14",
        "stoch_k_14",
        "stoch_d_14",
    ]
    assert result.index.equals(candles.index)
    assert result.iloc[-1].notna().all()


def test_compute_columns_mixes_price_and_indicators(candles: pd.DataFrame) -> None:
    result = compute_columns(candles, ["close", "rsi_14", "macd_hist"])
    assert list(result.columns) == ["close", "rsi_14", "macd_hist"]
    assert result["close"].equals(candles["close"].astype(float))
