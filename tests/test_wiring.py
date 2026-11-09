"""Offline tests for framework-independent API helpers and service wiring."""

import asyncio
import math

import pandas as pd
import pytest

from market_pulse.alerts import AlertRule
from market_pulse.api.container import build_container, build_provider
from market_pulse.api.schemas import AlertCreate
from market_pulse.api.serialization import alert_to_dict, frame_to_records
from market_pulse.auth import is_valid_api_key
from market_pulse.config import Settings
from market_pulse.providers import BinanceProvider, CSVProvider
from market_pulse.providers.cached import CachedProvider


def test_frame_to_records_maps_nan_and_timestamps() -> None:
    frame = pd.DataFrame(
        {
            "open_time": pd.to_datetime(["2025-01-01T00:00:00Z"], utc=True),
            "rsi_14": [math.nan],
            "close": [1.5],
        }
    )
    [row] = frame_to_records(frame)
    assert row["rsi_14"] is None
    assert row["close"] == 1.5
    assert row["open_time"].isoformat() == "2025-01-01T00:00:00+00:00"


def test_alert_to_dict() -> None:
    rule = AlertRule.create("ethusdt", "1d", "rsi_14 > 70 or macd_hist < 0", name="x")
    data = alert_to_dict(rule)
    assert data["symbol"] == "ETHUSDT"
    assert data["identifiers"] == ["rsi_14", "macd_hist"]


def test_api_key_validation() -> None:
    assert is_valid_api_key("k2", ["k1", "k2"])
    assert not is_valid_api_key("k3", ["k1", "k2"])
    assert not is_valid_api_key(None, ["k1"])
    assert not is_valid_api_key("", [])


def test_alert_create_schema_validation() -> None:
    from pydantic import ValidationError

    assert AlertCreate(symbol="BTCUSDT", expression="close > 1").interval == "1h"
    with pytest.raises(ValidationError):
        AlertCreate(symbol="BTC/USDT", expression="close > 1")
    with pytest.raises(ValidationError):
        AlertCreate(symbol="BTCUSDT", interval="7m", expression="close > 1")


def test_build_container_wires_services() -> None:
    settings = Settings(rate_limit_enabled=False)
    container = build_container(settings)
    assert isinstance(container.provider, CachedProvider)
    assert isinstance(container.provider.inner, CSVProvider)
    assert container.provider.synthetic is True
    assert container.limiter is None
    assert container.evaluator.provider is container.provider
    asyncio.run(container.aclose())

    assert build_container(Settings()).limiter is not None
    assert isinstance(build_provider(Settings(data_provider="binance")), BinanceProvider)
