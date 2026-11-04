from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Mapping
from typing import cast

from starlette.websockets import WebSocket, WebSocketDisconnect
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed
from websockets.typing import Origin


async def _admit_frame(websocket: WebSocket, is_active: Callable[[], bool] | None) -> bool:
    if is_active is not None and not is_active():
        with contextlib.suppress(RuntimeError):
            await websocket.close(code=4401)
        return False
    return True


async def _client_to_upstream(
    websocket: WebSocket,
    upstream: ClientConnection,
    is_active: Callable[[], bool] | None,
) -> None:
    while True:
        message = await websocket.receive()
        if message.get("type") == "websocket.disconnect":
            return
        if not await _admit_frame(websocket, is_active):
            return
        text = message.get("text")
        data = message.get("bytes")
        if isinstance(text, str):
            await upstream.send(text)
        elif isinstance(data, bytes):
            await upstream.send(data)


async def _upstream_to_client(
    websocket: WebSocket,
    upstream: ClientConnection,
    is_active: Callable[[], bool] | None,
) -> None:
    async for message in upstream:
        if not await _admit_frame(websocket, is_active):
            return
        if isinstance(message, str):
            await websocket.send_text(message)
        else:
            await websocket.send_bytes(bytes(message))


async def _relay_pair(
    websocket: WebSocket,
    upstream: ClientConnection,
    is_active: Callable[[], bool] | None,
) -> None:
    tasks = {
        asyncio.create_task(_client_to_upstream(websocket, upstream, is_active)),
        asyncio.create_task(_upstream_to_client(websocket, upstream, is_active)),
    }
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            with contextlib.suppress(WebSocketDisconnect):
                task.result()
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def relay_websocket(
    websocket: WebSocket,
    target_url: str,
    *,
    headers: Mapping[str, str] | None = None,
    origin: str | None = None,
    accept_downstream: bool = True,
    is_active: Callable[[], bool] | None = None,
) -> None:
    """Relay framing; the owning application may supply its admission predicate."""
    try:
        async with connect(
            target_url,
            additional_headers=dict(headers or {}),
            origin=cast(Origin | None, origin),
            proxy=None,
            max_size=None,
            open_timeout=10,
            close_timeout=5,
        ) as upstream:
            if accept_downstream:
                await websocket.accept()
            await _relay_pair(websocket, upstream, is_active)
            with contextlib.suppress(RuntimeError):
                await websocket.close(code=1000)
    except WebSocketDisconnect:
        return
    except ConnectionClosed as error:
        with contextlib.suppress(RuntimeError):
            await websocket.close(code=int(error.code), reason=str(error.reason or ""))
    except Exception:
        with contextlib.suppress(RuntimeError):
            await websocket.close(code=1011)
        raise
