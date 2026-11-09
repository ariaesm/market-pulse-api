"""Alert rule CRUD endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response, status

from market_pulse.alerts import AlertRule
from market_pulse.api.container import Container
from market_pulse.api.deps import get_container
from market_pulse.api.schemas import (
    SYMBOL_PATTERN,
    AlertCreate,
    AlertListResponse,
    AlertOut,
    ErrorResponse,
)
from market_pulse.api.serialization import alert_to_dict
from market_pulse.errors import SymbolNotFoundError

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.post(
    "",
    response_model=AlertOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create an alert rule",
    responses={
        404: {"model": ErrorResponse, "description": "Unknown symbol"},
        409: {"model": ErrorResponse, "description": "Alert limit reached"},
        422: {"model": ErrorResponse, "description": "Invalid rule expression"},
    },
)
async def create_alert(
    body: AlertCreate, container: Container = Depends(get_container)
) -> AlertOut:
    """Register a rule such as `rsi_14 < 30 and close > 50000`.

    Rules are evaluated in the background on the latest bar and fire once each time they
    change from false to true. Triggered alerts are streamed on `WS /v1/ws/alerts`.
    """
    rule = AlertRule.create(body.symbol, body.interval, body.expression, body.name)
    known = {info.symbol for info in await container.provider.list_symbols()}
    if rule.symbol not in known:
        raise SymbolNotFoundError(
            f"unknown symbol {rule.symbol!r}", details={"available": sorted(known)}
        )
    container.store.add(rule)
    return AlertOut(**alert_to_dict(rule))


@router.get("", response_model=AlertListResponse, summary="List alert rules")
async def list_alerts(
    symbol: Annotated[str | None, Query(pattern=SYMBOL_PATTERN)] = None,
    container: Container = Depends(get_container),
) -> AlertListResponse:
    """List registered alert rules, optionally filtered by symbol."""
    rules = container.store.list(symbol)
    return AlertListResponse(count=len(rules), alerts=[AlertOut(**alert_to_dict(r)) for r in rules])


@router.delete(
    "/{alert_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an alert rule",
    responses={404: {"model": ErrorResponse, "description": "Alert not found"}},
)
async def delete_alert(
    alert_id: Annotated[str, Path(pattern=r"^[0-9a-f]{32}$")],
    container: Container = Depends(get_container),
) -> Response:
    """Delete a rule by id."""
    container.store.delete(alert_id)
    container.evaluator.engine.forget(alert_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
