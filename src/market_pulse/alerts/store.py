"""In-memory alert rule repository."""

from __future__ import annotations

from market_pulse.alerts.models import AlertRule
from market_pulse.errors import AppError, NotFoundError


class AlertLimitError(AppError):
    """Too many alert rules registered."""

    status_code = 409
    code = "alert_limit_reached"


class AlertStore:
    """Process-local storage for alert rules (insertion ordered).

    Rules are lost on restart; a persistent store can implement the same methods.
    """

    def __init__(self, max_rules: int = 500) -> None:
        self.max_rules = max_rules
        self._rules: dict[str, AlertRule] = {}

    def __len__(self) -> int:
        return len(self._rules)

    def add(self, rule: AlertRule) -> AlertRule:
        """Store a rule; raises :class:`AlertLimitError` when full."""
        if len(self._rules) >= self.max_rules:
            raise AlertLimitError(f"at most {self.max_rules} alert rules are allowed")
        self._rules[rule.id] = rule
        return rule

    def get(self, alert_id: str) -> AlertRule:
        """Return a rule or raise :class:`NotFoundError`."""
        try:
            return self._rules[alert_id]
        except KeyError:
            raise NotFoundError(f"alert {alert_id!r} not found") from None

    def list(self, symbol: str | None = None) -> list[AlertRule]:
        """All rules, optionally filtered by symbol."""
        rules = list(self._rules.values())
        if symbol:
            rules = [r for r in rules if r.symbol == symbol.upper()]
        return rules

    def delete(self, alert_id: str) -> AlertRule:
        """Remove and return a rule or raise :class:`NotFoundError`."""
        rule = self.get(alert_id)
        del self._rules[alert_id]
        return rule
