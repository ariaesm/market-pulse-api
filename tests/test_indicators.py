"""Indicator tests against small, hand-computed fixtures."""

import math

import numpy as np
import pandas as pd
import pytest

from market_pulse.indicators import core


def _s(values: list[float]) -> pd.Series:
    return pd.Series(values, dtype=float)


def _assert_series(actual: pd.Series, expected: list[float]) -> None:
    assert len(actual) == len(expected)
    for got, want in zip(actual.tolist(), expected, strict=True):
        if math.isnan(want):
            assert math.isnan(got), f"expected NaN, got {got}"
        else:
            assert got == pytest.approx(want, abs=1e-6)


NAN = float("nan")


def test_sma_hand_computed() -> None:
    _assert_series(core.sma(_s([1, 2, 3, 4, 5]), 3), [NAN, NAN, 2, 3, 4])


def test_ema_seeded_with_sma() -> None:
    # alpha = 0.5, seed = mean(1, 2, 3) = 2
    _assert_series(core.ema(_s([1, 2, 3, 4, 5, 6]), 3), [NAN, NAN, 2, 3, 4, 5])


def test_ema_nonlinear_input() -> None:
    # alpha = 2/3, seed = mean(2, 4) = 3
    # 2/3*6 + 1/3*3 = 5 ; 2/3*8 + 1/3*5 = 7 ; 2/3*12 + 1/3*7 = 31/3
    _assert_series(core.ema(_s([2, 4, 6, 8, 12]), 2), [NAN, 3, 5, 7, 31 / 3])


def test_ema_skips_leading_nans() -> None:
    _assert_series(core.ema(_s([NAN, NAN, 1, 2, 3, 4]), 3), [NAN, NAN, NAN, NAN, 2, 3])


def test_ema_too_short_is_all_nan() -> None:
    assert core.ema(_s([1, 2]), 3).isna().all()


def test_rsi_wilder_hand_computed() -> None:
    # deltas: +1 +1 -1 +2 -1, period 3
    # seed: avg_gain = 2/3, avg_loss = 1/3 -> RS 2 -> 66.667
    # next: gain (2/3*2 + 2)/3 = 10/9, loss (1/3*2)/3 = 2/9 -> RS 5 -> 83.333
    # next: gain 20/27, loss 13/27 -> RS 20/13 -> 60.606
    result = core.rsi(_s([10, 11, 12, 11, 13, 12]), 3)
    _assert_series(result, [NAN, NAN, NAN, 200 / 3, 250 / 3, 100 - 1300 / 33])


def test_rsi_edge_cases() -> None:
    assert core.rsi(_s([1, 2, 3, 4, 5]), 3).iloc[-1] == 100.0
    assert core.rsi(_s([5, 5, 5, 5, 5]), 3).iloc[-1] == 50.0
    assert core.rsi(_s([5, 4, 3, 2, 1]), 3).iloc[-1] == pytest.approx(0.0)
    assert core.rsi(_s([1, 2, 3]), 3).isna().all()


def test_rsi_bounded_on_random_walk() -> None:
    rng = np.random.default_rng(7)
    close = pd.Series(100 + rng.normal(0, 1, 500).cumsum())
    values = core.rsi(close, 14).dropna()
    assert len(values) == 500 - 14
    assert values.between(0, 100).all()


def test_macd_on_linear_ramp_is_constant() -> None:
    # For x_t = t an SMA-seeded EMA(n) equals t - (n - 1) / 2 exactly,
    # so MACD(12, 26) = 12.5 - 5.5 = 7 and the signal converges to 7 immediately.
    close = pd.Series(np.arange(60, dtype=float))
    result = core.macd(close)
    assert result["macd"].iloc[:25].isna().all()
    assert np.allclose(result["macd"].iloc[25:], 7.0)
    assert result["signal"].iloc[:33].isna().all()
    assert np.allclose(result["signal"].iloc[33:], 7.0)
    assert np.allclose(result["hist"].iloc[33:], 0.0)


def test_macd_rejects_bad_periods() -> None:
    with pytest.raises(ValueError, match="fast"):
        core.macd(_s([1, 2, 3]), fast=26, slow=12)


def test_bollinger_bands_population_std() -> None:
    bands = core.bollinger_bands(_s([1, 2, 3, 4, 5]), period=5)
    width = 2 * math.sqrt(2)
    assert bands["middle"].iloc[-1] == pytest.approx(3.0)
    assert bands["upper"].iloc[-1] == pytest.approx(3 + width)
    assert bands["lower"].iloc[-1] == pytest.approx(3 - width)
    assert bands.iloc[:4].isna().all().all()


def _hlc() -> tuple[pd.Series, pd.Series, pd.Series]:
    high = _s([10, 11, 14, 13, 12])
    low = _s([8, 9, 12, 11, 9])
    close = _s([9, 10.5, 13, 11.5, 10])
    return high, low, close


def test_true_range_uses_gaps() -> None:
    # bar2 gaps up from 10.5: max(2, |14-10.5|, |12-10.5|) = 3.5
    _assert_series(core.true_range(*_hlc()), [2, 2, 3.5, 2, 3])


def test_atr_wilder_hand_computed() -> None:
    # TR = [2, 2, 3.5, 2, 3]; seed = 7.5/3 = 2.5; (2.5*2+2)/3 = 7/3; (7/3*2+3)/3 = 23/9
    _assert_series(core.atr(*_hlc(), period=3), [NAN, NAN, 2.5, 7 / 3, 23 / 9])


def test_stochastic_hand_computed() -> None:
    high = _s([10, 11, 12, 13, 12])
    low = _s([8, 9, 10, 11, 9])
    close = _s([9, 10, 11, 12, 10])
    result = core.stochastic(high, low, close, period=3, smooth_d=2)
    _assert_series(result["k"], [NAN, NAN, 75, 75, 25])
    _assert_series(result["d"], [NAN, NAN, NAN, 75, 50])


def test_stochastic_flat_window_is_50() -> None:
    flat = _s([5, 5, 5, 5])
    result = core.stochastic(flat, flat, flat, period=3, smooth_d=1)
    _assert_series(result["k"], [NAN, NAN, 50, 50])


@pytest.mark.parametrize("period", [0, -1])
def test_invalid_period_rejected(period: int) -> None:
    with pytest.raises(ValueError, match="period"):
        core.sma(_s([1, 2, 3]), period)
