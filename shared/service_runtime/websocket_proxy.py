from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Mapping

from starlette.websockets import WebSocket, WebSocketDisconnect
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed
from websockets.typing import Origin


def _upstream_origin(origin: str | None) -> Origin | None:
    return None if origin is None else Origin(origin)


async def _client_to_upstream(websocket: WebSocket, upstream: ClientConnection) -> None:
    while True:
        message = await websocket.receive()
        kind = message.get("type")
        if kind == "websocket.disconnect":
            return
        text = message.get("text")
        data = message.get("bytes")
        if isinstance(text, str):
            await upstream.send(text)
        elif isinstance(data, bytes):
            await upstream.send(data)


async def _upstream_to_client(websocket: WebSocket, upstream: ClientConnection) -> None:
    async for message in upstream:
        if isinstance(message, str):
            await websocket.send_text(message)
        else:
            await websocket.send_bytes(bytes(message))


async def relay_websocket(
    websocket: WebSocket,
    target_url: str,
    *,
    headers: Mapping[str, str] | None = None,
    origin: str | None = None,
    accept_downstream: bool = True,
) -> None:
    """Relay one authenticated Starlette WebSocket to an internal WebSocket."""

    try:
        async with connect(
            target_url,
            additional_headers=dict(headers or {}),
            origin=_upstream_origin(origin),
            proxy=None,
            max_size=None,
            open_timeout=10,
            close_timeout=5,
        ) as upstream:
            if accept_downstream:
                await websocket.accept()
            tasks = {
                asyncio.create_task(
                    _client_to_upstream(websocket, upstream), name="websocket-client-upstream"
                ),
                asyncio.create_task(
                    _upstream_to_client(websocket, upstream), name="websocket-upstream-client"
                ),
            }
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                with contextlib.suppress(WebSocketDisconnect):
                    task.result()
            with contextlib.suppress(RuntimeError):
                await websocket.close(code=1000)
    except WebSocketDisconnect:
        return
    except ConnectionClosed as exc:
        with contextlib.suppress(RuntimeError):
            await websocket.close(code=int(exc.code), reason=str(exc.reason or ""))
        return
    except Exception:
        with contextlib.suppress(RuntimeError):
            await websocket.close(code=1011)
        raise
