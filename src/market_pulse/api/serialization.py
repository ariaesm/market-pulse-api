"""Convert domain objects to response-friendly structures (framework independent)."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from market_pulse.alerts import AlertRule


def _clean(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    return value


def frame_to_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Rows as dicts with ``NaN``/``inf`` mapped to ``None`` and timestamps to datetimes."""
    columns = list(frame.columns)
    return [
        {col: _clean(val) for col, val in zip(columns, row, strict=True)}
        for row in frame.itertuples(index=False, name=None)
    ]


def alert_to_dict(rule: AlertRule) -> dict[str, Any]:
    """Public representation of an alert rule."""
    return {
        "id": rule.id,
        "symbol": rule.symbol,
        "interval": rule.interval,
        "expression": rule.expression,
        "name": rule.name,
        "identifiers": list(rule.rule.identifiers),
        "created_at": rule.created_at,
    }
