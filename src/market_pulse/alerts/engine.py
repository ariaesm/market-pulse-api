"""Edge-triggered evaluation of alert rules against candles."""

from __future__ import annotations

import pandas as pd

from market_pulse.alerts.models import AlertRule, TriggeredAlert
from market_pulse.indicators.registry import compute_columns


class AlertEngine:
    """Evaluate rules and emit an event only on a false -> true transition.

    A rule that stays true does not fire again until it has been false at least once,
    which prevents a stream of duplicate alerts on every evaluation tick.
    """

    def __init__(self) -> None:
        self._state: dict[str, bool] = {}

    def latest_values(self, rule: AlertRule, candles: pd.DataFrame) -> dict[str, float]:
        """Values of every identifier in ``rule`` on the latest bar."""
        if candles.empty:
            return {}
        frame = compute_columns(candles, rule.rule.identifiers)
        return {col: float(frame[col].iloc[-1]) for col in frame.columns}

    def evaluate(self, rule: AlertRule, candles: pd.DataFrame) -> TriggeredAlert | None:
        """Evaluate ``rule`` on the latest bar and return an event on a rising edge."""
        if candles.empty:
            return None
        values = self.latest_values(rule, candles)
        active = rule.rule.evaluate(values)
        was_active = self._state.get(rule.id, False)
        self._state[rule.id] = active
        if not active or was_active:
            return None
        return TriggeredAlert(
            alert_id=rule.id,
            name=rule.name,
            symbol=rule.symbol,
            interval=rule.interval,
            expression=rule.expression,
            values=dict(values),
            bar_time=candles["open_time"].iloc[-1].to_pydatetime(),
        )

    def forget(self, alert_id: str) -> None:
        """Drop edge-trigger state for a deleted rule."""
        self._state.pop(alert_id, None)
