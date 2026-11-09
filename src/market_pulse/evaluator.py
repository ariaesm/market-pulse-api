"""Background task that periodically evaluates alert rules and publishes triggers."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import defaultdict
from datetime import datetime

from market_pulse.alerts import AlertEngine, AlertRule, AlertStore, TriggeredAlert
from market_pulse.alerts.models import utcnow
from market_pulse.errors import AppError
from market_pulse.providers.base import MarketDataProvider
from market_pulse.streaming import AlertBroker

logger = logging.getLogger(__name__)


class AlertEvaluator:
    """Evaluate all stored rules every ``interval_seconds`` seconds.

    Rules are grouped by ``(symbol, interval)`` so each series is fetched once per tick.
    A failing series is logged and skipped; it never stops the loop.
    """

    def __init__(
        self,
        provider: MarketDataProvider,
        store: AlertStore,
        broker: AlertBroker,
        *,
        engine: AlertEngine | None = None,
        interval_seconds: float = 15.0,
        lookback: int = 300,
    ) -> None:
        self.provider = provider
        self.store = store
        self.broker = broker
        self.engine = engine or AlertEngine()
        self.interval_seconds = interval_seconds
        self.lookback = lookback
        self.last_run_at: datetime | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        """Whether the background loop is active."""
        return self._task is not None and not self._task.done()

    async def run_once(self) -> list[TriggeredAlert]:
        """Evaluate every rule once and publish triggered alerts."""
        groups: dict[tuple[str, str], list[AlertRule]] = defaultdict(list)
        for rule in self.store.list():
            groups[(rule.symbol, rule.interval)].append(rule)

        triggered: list[TriggeredAlert] = []
        for (symbol, interval), rules in groups.items():
            try:
                candles = await self.provider.get_ohlcv(symbol, interval, self.lookback)
            except AppError as exc:
                logger.warning(
                    "alert evaluation skipped",
                    extra={"symbol": symbol, "interval": interval, "error": exc.message},
                )
                continue
            for rule in rules:
                event = self.engine.evaluate(rule, candles)
                if event is not None:
                    triggered.append(event)
                    delivered = self.broker.publish(event.to_dict())
                    logger.info(
                        "alert triggered",
                        extra={"alert_id": rule.id, "symbol": symbol, "subscribers": delivered},
                    )
        self.last_run_at = utcnow()
        return triggered

    async def run_forever(self) -> None:
        """Loop until cancelled, never letting one failure kill the task."""
        while True:
            try:
                await self.run_once()
            except Exception:
                logger.exception("alert evaluation failed")
            await asyncio.sleep(self.interval_seconds)

    def start(self) -> None:
        """Start the background loop on the running event loop."""
        if not self.running:
            self._task = asyncio.create_task(self.run_forever(), name="alert-evaluator")

    async def stop(self) -> None:
        """Cancel the background loop and wait for it to finish."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
