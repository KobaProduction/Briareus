from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Mapping
from typing import Protocol

from starlette.websockets import WebSocket, WebSocketDisconnect

from control_panel_api.application.identity import PanelIdentityService
from control_panel_api.domain.identity import PanelIdentitySession


class WebSocketRelay(Protocol):
    async def __call__(
        self,
        websocket: WebSocket,
        target_url: str,
        *,
        headers: Mapping[str, str] | None = None,
        origin: str | None = None,
        accept_downstream: bool = True,
        is_active: Callable[[], bool] | None = None,
    ) -> None: ...


async def identity_socket_active(
    websocket: WebSocket,
    identity: PanelIdentityService,
    identifier: str,
) -> bool:
    if identity.current(identifier) is not None:
        return True
    with contextlib.suppress(RuntimeError):
        await websocket.close(code=4401)
    return False


async def watch_identity_session(
    websocket: WebSocket,
    identity: PanelIdentityService,
    identifier: str,
    stopped: asyncio.Event,
) -> None:
    while not stopped.is_set():
        if not await identity_socket_active(websocket, identity, identifier):
            return
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stopped.wait(), timeout=1)


async def relay_identity_socket(
    websocket: WebSocket,
    target_url: str,
    *,
    identity: PanelIdentityService,
    session: PanelIdentitySession,
    headers: Mapping[str, str],
    relay: WebSocketRelay,
) -> None:
    def is_active() -> bool:
        return identity.current(session.identifier) is not None

    relay_task = asyncio.create_task(
        relay(
            websocket,
            target_url,
            headers=headers,
            is_active=is_active,
        )
    )
    stopped = asyncio.Event()
    watcher = asyncio.create_task(
        watch_identity_session(websocket, identity, session.identifier, stopped)
    )
    tasks = {relay_task, watcher}
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            with contextlib.suppress(WebSocketDisconnect):
                task.result()
    finally:
        stopped.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
