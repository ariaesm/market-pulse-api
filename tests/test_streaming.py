import asyncio

from market_pulse.alerts import AlertRule, AlertStore
from market_pulse.config import DEFAULT_DATA_DIR
from market_pulse.evaluator import AlertEvaluator
from market_pulse.providers import CSVProvider
from market_pulse.streaming import AlertBroker


def test_broker_fans_out_with_symbol_filter() -> None:
    async def scenario() -> None:
        broker = AlertBroker()
        everything = broker.subscribe()
        btc_only = broker.subscribe("btcusdt")
        assert broker.publish({"symbol": "ETHUSDT", "n": 1}) == 1
        assert broker.publish({"symbol": "BTCUSDT", "n": 2}) == 2
        assert (await everything.get())["n"] == 1
        assert (await everything.get())["n"] == 2
        assert (await btc_only.get())["n"] == 2
        broker.unsubscribe(btc_only)
        broker.unsubscribe(btc_only)
        assert broker.subscriber_count == 1

    asyncio.run(scenario())


def test_slow_subscriber_drops_oldest() -> None:
    async def scenario() -> None:
        broker = AlertBroker(queue_size=2)
        sub = broker.subscribe()
        for n in range(4):
            broker.publish({"n": n})
        assert sub.dropped == 2
        assert [(await sub.get())["n"] for _ in range(2)] == [2, 3]

    asyncio.run(scenario())


def test_evaluator_publishes_triggered_alerts_once() -> None:
    async def scenario() -> None:
        store = AlertStore()
        broker = AlertBroker()
        always = store.add(AlertRule.create("BTCUSDT", "1h", "close > 0", name="always"))
        store.add(AlertRule.create("BTCUSDT", "1h", "close < 0"))
        store.add(AlertRule.create("DOGEUSDT", "1h", "close > 0"))  # unknown symbol: skipped
        evaluator = AlertEvaluator(CSVProvider(DEFAULT_DATA_DIR), store, broker)
        sub = broker.subscribe()

        first = await evaluator.run_once()
        assert [e.alert_id for e in first] == [always.id]
        event = await sub.get()
        assert event["name"] == "always"
        assert event["values"]["close"] > 0
        assert evaluator.last_run_at is not None
        assert await evaluator.run_once() == []  # edge-triggered: no repeat

    asyncio.run(scenario())


def test_evaluator_start_and_stop() -> None:
    async def scenario() -> None:
        evaluator = AlertEvaluator(
            CSVProvider(DEFAULT_DATA_DIR), AlertStore(), AlertBroker(), interval_seconds=0.01
        )
        evaluator.start()
        await asyncio.sleep(0.05)
        assert evaluator.running
        assert evaluator.last_run_at is not None
        await evaluator.stop()
        assert not evaluator.running

    asyncio.run(scenario())
