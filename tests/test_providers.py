import asyncio
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from market_pulse.config import DEFAULT_DATA_DIR
from market_pulse.errors import ProviderError, SymbolNotFoundError, UnsupportedIntervalError
from market_pulse.providers import (
    BinanceProvider,
    CSVProvider,
    candles_from_payload,
    candles_to_payload,
    parse_klines,
)

KLINES = [
    [
        1735689600000,
        "100.0",
        "110.0",
        "95.0",
        "105.0",
        "12.5",
        1735693199999,
        "0",
        10,
        "0",
        "0",
        "0",
    ],
    [
        1735693200000,
        "105.0",
        "108.0",
        "101.0",
        "102.0",
        "8.0",
        1735696799999,
        "0",
        7,
        "0",
        "0",
        "0",
    ],
]


def test_csv_provider_lists_bundled_synthetic_symbols() -> None:
    provider = CSVProvider(DEFAULT_DATA_DIR)
    symbols = asyncio.run(provider.list_symbols())
    by_name = {s.symbol: s for s in symbols}
    assert {"BTCUSDT", "ETHUSDT", "SOLUSDT"} <= set(by_name)
    btc = by_name["BTCUSDT"]
    assert btc.intervals == ("1h", "1d")
    assert (btc.base, btc.quote) == ("BTC", "USDT")
    assert btc.synthetic is True


def test_csv_provider_returns_tail_in_canonical_schema() -> None:
    provider = CSVProvider(DEFAULT_DATA_DIR)
    frame = asyncio.run(provider.get_ohlcv("btcusdt", "1h", 50))
    assert list(frame.columns) == ["open_time", "open", "high", "low", "close", "volume"]
    assert len(frame) == 50
    assert str(frame["open_time"].dt.tz) == "UTC"
    assert frame["open_time"].is_monotonic_increasing
    assert (frame["high"] >= frame[["open", "close"]].max(axis=1)).all()
    assert (frame["low"] <= frame[["open", "close"]].min(axis=1)).all()


def test_csv_provider_errors(tmp_path: Path) -> None:
    provider = CSVProvider(DEFAULT_DATA_DIR)
    with pytest.raises(SymbolNotFoundError):
        asyncio.run(provider.get_ohlcv("DOGEUSDT", "1h", 10))
    with pytest.raises(UnsupportedIntervalError):
        asyncio.run(provider.get_ohlcv("BTCUSDT", "5m", 10))
    with pytest.raises(ProviderError):
        asyncio.run(CSVProvider(tmp_path / "missing").list_symbols())


def test_csv_provider_reports_malformed_files(tmp_path: Path) -> None:
    (tmp_path / "BADUSDT_1h.csv").write_text("open_time,open\n2025-01-01,1\n")
    with pytest.raises(ProviderError, match=r"BADUSDT_1h\.csv"):
        asyncio.run(CSVProvider(tmp_path).get_ohlcv("BADUSDT", "1h", 5))


def test_parse_klines() -> None:
    frame = parse_klines(KLINES)
    assert frame["open_time"].iloc[0] == pd.Timestamp("2025-01-01T00:00:00Z")
    assert frame["close"].tolist() == [105.0, 102.0]
    assert frame["volume"].dtype == float
    assert parse_klines([]).empty
    with pytest.raises(ProviderError):
        parse_klines([["not-a-timestamp", "1", "1", "1", "1", "1"]])


def test_payload_roundtrip() -> None:
    frame = parse_klines(KLINES)
    payload = candles_to_payload(frame)
    assert payload["open_time"] == [1735689600000, 1735693200000]
    pd.testing.assert_frame_equal(candles_from_payload(payload), frame)


class FakeResponse:
    def __init__(self, status_code: int, body: Any) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> Any:
        return self._body


class FakeClient:
    """Stand-in for ``httpx.AsyncClient`` that records calls."""

    def __init__(self, response: FakeResponse | Exception) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def get(self, url: str, *, params: dict[str, Any] | None = None) -> FakeResponse:
        self.calls.append((url, params))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_binance_provider_requests_klines() -> None:
    client = FakeClient(FakeResponse(200, KLINES))
    provider = BinanceProvider("https://example.test/", ["BTCUSDT"], client=client)
    frame = asyncio.run(provider.get_ohlcv("btcusdt", "1h", 5000))
    assert len(frame) == 2
    url, params = client.calls[0]
    assert url == "https://example.test/api/v3/klines"
    assert params == {"symbol": "BTCUSDT", "interval": "1h", "limit": 1000}


def test_binance_provider_maps_errors() -> None:
    invalid = FakeClient(FakeResponse(400, {"code": -1121, "msg": "Invalid symbol."}))
    with pytest.raises(SymbolNotFoundError):
        asyncio.run(BinanceProvider(symbols=[], client=invalid).get_ohlcv("NOPE", "1h", 5))

    server_error = FakeClient(FakeResponse(503, {"msg": "busy"}))
    with pytest.raises(ProviderError, match="503"):
        asyncio.run(BinanceProvider(client=server_error).get_ohlcv("BTCUSDT", "1h", 5))

    network = FakeClient(ConnectionError("boom"))
    with pytest.raises(ProviderError, match="boom"):
        asyncio.run(BinanceProvider(client=network).get_ohlcv("BTCUSDT", "1h", 5))

    with pytest.raises(UnsupportedIntervalError):
        asyncio.run(BinanceProvider(client=network).get_ohlcv("BTCUSDT", "7m", 5))
