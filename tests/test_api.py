"""HTTP and WebSocket integration tests (run in CI where FastAPI/httpx are installed)."""

from collections.abc import Iterator

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from market_pulse.api.app import create_app
from market_pulse.config import Settings

BASE_SETTINGS = {"environment": "test", "alert_eval_enabled": False, "rate_limit_enabled": False}


def make_client(**overrides: object) -> TestClient:
    return TestClient(create_app(Settings(**{**BASE_SETTINGS, **overrides})))


@pytest.fixture
def client() -> Iterator[TestClient]:
    with make_client() as c:
        yield c


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["provider"] == "csv"
    assert body["synthetic_data"] is True
    assert body["auth_enabled"] is False
    assert "x-request-id" in response.headers


def test_symbols(client: TestClient) -> None:
    body = client.get("/v1/symbols").json()
    names = {s["symbol"] for s in body["symbols"]}
    assert {"BTCUSDT", "ETHUSDT", "SOLUSDT"} <= names
    assert all(s["synthetic"] for s in body["symbols"])


def test_ohlcv(client: TestClient) -> None:
    response = client.get("/v1/ohlcv/btcusdt", params={"interval": "1d", "limit": 5})
    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "BTCUSDT"
    assert body["count"] == 5
    assert set(body["candles"][0]) == {"open_time", "open", "high", "low", "close", "volume"}


def test_indicators_are_warmed_up(client: TestClient) -> None:
    response = client.get(
        "/v1/indicators/BTCUSDT", params={"names": "rsi,ema_20,macd,bbands,atr", "limit": 10}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["indicators"] == ["rsi_14", "ema_20", "macd", "bbands_20", "atr_14"]
    assert body["count"] == 10
    last = body["data"][-1]
    for column in body["columns"]:
        assert last[column] is not None
    assert 0 <= last["rsi_14"] <= 100


def test_signals(client: TestClient) -> None:
    body = client.get("/v1/signals/ETHUSDT").json()
    assert body["bias"] in {"bullish", "bearish", "neutral"}
    assert "Not financial advice" in body["disclaimer"]
    for signal in body["signals"]:
        assert signal["direction"] in {"bullish", "bearish"}


@pytest.mark.parametrize(
    ("path", "status", "code"),
    [
        ("/v1/ohlcv/DOGEUSDT", 404, "symbol_not_found"),
        ("/v1/ohlcv/BTCUSDT?interval=5m", 422, "unsupported_interval"),
        ("/v1/ohlcv/BTCUSDT?interval=7m", 422, "validation_error"),
        ("/v1/ohlcv/BTCUSDT?limit=0", 422, "validation_error"),
        ("/v1/indicators/BTCUSDT?names=foo", 422, "invalid_indicator"),
        ("/v1/nope", 404, "not_found"),
    ],
)
def test_error_envelope(client: TestClient, path: str, status: int, code: str) -> None:
    response = client.get(path)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


def test_alert_crud(client: TestClient) -> None:
    created = client.post(
        "/v1/alerts",
        json={"symbol": "btcusdt", "interval": "1h", "expression": "rsi_14 < 30", "name": "dip"},
    )
    assert created.status_code == 201
    alert = created.json()
    assert alert["symbol"] == "BTCUSDT"
    assert alert["identifiers"] == ["rsi_14"]

    listing = client.get("/v1/alerts", params={"symbol": "BTCUSDT"}).json()
    assert listing["count"] == 1

    assert client.delete(f"/v1/alerts/{alert['id']}").status_code == 204
    assert client.delete(f"/v1/alerts/{alert['id']}").status_code == 404
    assert client.get("/v1/alerts").json()["count"] == 0


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"symbol": "BTCUSDT", "expression": "rsi_14 <"}, "invalid_rule"),
        ({"symbol": "BTCUSDT", "expression": "magic > 1"}, "invalid_indicator"),
        ({"symbol": "DOGEUSDT", "expression": "close > 1"}, "symbol_not_found"),
        ({"symbol": "BTCUSDT"}, "validation_error"),
    ],
)
def test_alert_validation(client: TestClient, payload: dict[str, str], code: str) -> None:
    response = client.post("/v1/alerts", json=payload)
    assert response.json()["error"]["code"] == code


def test_api_key_auth() -> None:
    with make_client(api_keys=["secret"]) as c:
        assert c.get("/health").status_code == 200
        denied = c.get("/v1/symbols")
        assert denied.status_code == 401
        assert denied.json()["error"]["code"] == "unauthorized"
        assert c.get("/v1/symbols", headers={"X-API-Key": "wrong"}).status_code == 401
        assert c.get("/v1/symbols", headers={"X-API-Key": "secret"}).status_code == 200


def test_rate_limit() -> None:
    with make_client(rate_limit_enabled=True, rate_limit_burst=2, rate_limit_per_minute=1) as c:
        assert c.get("/v1/symbols").status_code == 200
        assert c.get("/v1/symbols").status_code == 200
        limited = c.get("/v1/symbols")
        assert limited.status_code == 429
        assert limited.json()["error"]["code"] == "rate_limited"
        assert "retry-after" in limited.headers
        assert c.get("/health").status_code == 200


def test_openapi_has_tags_and_examples(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert {t["name"] for t in schema["tags"]} >= {"market data", "indicators", "alerts"}
    assert "/v1/indicators/{symbol}" in schema["paths"]
    assert schema["components"]["schemas"]["AlertCreate"]["examples"]


def test_websocket_streams_triggered_alerts(client: TestClient) -> None:
    alert = client.post(
        "/v1/alerts", json={"symbol": "BTCUSDT", "expression": "close > 0", "name": "always"}
    ).json()
    evaluator = client.app.state.container.evaluator  # type: ignore[attr-defined]
    with client.websocket_connect("/v1/ws/alerts?symbol=BTCUSDT") as ws:
        assert ws.receive_json() == {"type": "subscribed", "symbol": "BTCUSDT"}
        client.portal.call(evaluator.run_once)  # type: ignore[union-attr]
        event = ws.receive_json()
    assert event["type"] == "alert.triggered"
    assert event["alert_id"] == alert["id"]
    assert event["name"] == "always"


def test_websocket_requires_key_when_auth_enabled() -> None:
    from starlette.websockets import WebSocketDisconnect

    with make_client(api_keys=["secret"]) as c:
        with pytest.raises(WebSocketDisconnect), c.websocket_connect("/v1/ws/alerts") as ws:
            ws.receive_json()
        with c.websocket_connect("/v1/ws/alerts?api_key=secret") as ws:
            assert ws.receive_json()["type"] == "subscribed"
