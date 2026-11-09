"""WebSocket endpoint streaming triggered alerts."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Annotated

from fastapi import APIRouter, Query, WebSocket, status
from starlette.websockets import WebSocketDisconnect

from market_pulse.api.container import Container
from market_pulse.auth import is_valid_api_key
from market_pulse.streaming import Subscription

logger = logging.getLogger(__name__)

router = APIRouter(tags=["alerts"])


async def _pump(websocket: WebSocket, sub: Subscription) -> None:
    """Forward broker events to the client until cancelled or the socket fails."""
    while True:
        event = await sub.get()
        await websocket.send_json(event)


async def _drain(websocket: WebSocket) -> None:
    """Consume (and ignore) client messages; return when the client disconnects."""
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return


@router.websocket("/ws/alerts")
async def alerts_stream(
    websocket: WebSocket,
    symbol: Annotated[str | None, Query(pattern=r"^[A-Za-z0-9]{2,20}$")] = None,
    api_key: Annotated[str | None, Query()] = None,
) -> None:
    """Stream `alert.triggered` events as JSON.

    Optional `symbol` filters events. When auth is enabled, pass the key in the
    `X-API-Key` header or the `api_key` query parameter. The first message is a
    `{"type": "subscribed", ...}` acknowledgement.
    """
    container: Container = websocket.app.state.container
    settings = container.settings
    if settings.auth_enabled:
        supplied = websocket.headers.get("x-api-key") or api_key
        if not is_valid_api_key(supplied, settings.api_keys):
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

    # Subscribe before accepting so no event published after the handshake is missed.
    sub = container.broker.subscribe(symbol)
    try:
        await websocket.accept()
        await websocket.send_json({"type": "subscribed", "symbol": sub.symbol})
        tasks = {
            asyncio.create_task(_pump(websocket, sub)),
            asyncio.create_task(_drain(websocket)),
        }
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, WebSocketDisconnect):
                await task
        for task in done:
            exc = task.exception()
            if exc is not None and not isinstance(exc, WebSocketDisconnect):
                logger.warning("websocket stream ended with error", exc_info=exc)
    except WebSocketDisconnect:
        pass
    finally:
        container.broker.unsubscribe(sub)
