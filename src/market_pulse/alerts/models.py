"""Alert rule and triggered-alert domain models."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from market_pulse.indicators.registry import spec_for_column
from market_pulse.providers.base import validate_interval
from market_pulse.rules import Rule, parse_rule


def utcnow() -> datetime:
    """Timezone-aware current UTC time."""
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class AlertRule:
    """A user-defined alert: evaluate ``expression`` on ``symbol``/``interval`` candles."""

    id: str
    symbol: str
    interval: str
    expression: str
    rule: Rule
    name: str | None = None
    created_at: datetime = field(default_factory=utcnow)

    @classmethod
    def create(
        cls, symbol: str, interval: str, expression: str, name: str | None = None
    ) -> AlertRule:
        """Validate inputs and build a new rule with a random id.

        Raises:
            RuleSyntaxError: the expression does not parse.
            InvalidIndicatorError: the expression references an unknown indicator.
            UnsupportedIntervalError: the interval is not supported.
        """
        validate_interval(interval)
        rule = parse_rule(expression)
        for identifier in rule.identifiers:
            spec_for_column(identifier)
        return cls(
            id=uuid.uuid4().hex,
            symbol=symbol.upper(),
            interval=interval,
            expression=str(rule),
            rule=rule,
            name=name,
        )


@dataclass(frozen=True, slots=True)
class TriggeredAlert:
    """Event emitted when an alert rule transitions from false to true."""

    alert_id: str
    name: str | None
    symbol: str
    interval: str
    expression: str
    values: dict[str, float | None]
    bar_time: datetime
    triggered_at: datetime = field(default_factory=utcnow)

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly representation used on the WebSocket."""
        return {
            "type": "alert.triggered",
            "alert_id": self.alert_id,
            "name": self.name,
            "symbol": self.symbol,
            "interval": self.interval,
            "expression": self.expression,
            "values": {
                k: (None if v is None or math.isnan(v) else v) for k, v in self.values.items()
            },
            "bar_time": self.bar_time.isoformat(),
            "triggered_at": self.triggered_at.isoformat(),
        }
