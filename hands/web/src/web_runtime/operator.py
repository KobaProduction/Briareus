"""Authenticated WebSocket boundary for the existing browser operator protocol."""

from __future__ import annotations

import hmac
import json
from contextlib import suppress

from pydantic import ValidationError
from starlette.websockets import WebSocket, WebSocketDisconnect

from web_runtime.application.operator_session import OperatorSession
from web_runtime.domain.operator import OperatorViolation
from web_runtime.infrastructure.browser_operations import BrowserError
from web_runtime.infrastructure.operator_browser import BrowserOperator
from web_runtime.infrastructure.operator_codec import decode_command
from web_runtime.infrastructure.operator_events import OperatorErrorEvent
from web_runtime.infrastructure.operator_runtime import OperatorBrowserRuntime
from web_runtime.infrastructure.operator_stream import BrowserOperatorEvents


def _bearer_token(websocket: WebSocket) -> str:
    authorization = websocket.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    return token.strip() if scheme.casefold() == "bearer" else ""


async def _messages(websocket: WebSocket, session: OperatorSession) -> None:
    while True:
        raw = await websocket.receive_text()
        try:
            command = decode_command(raw)
        except json.JSONDecodeError:
            await websocket.send_text(OperatorErrorEvent(message="invalid JSON").model_dump_json())
            continue
        except ValidationError:
            await websocket.send_text(
                OperatorErrorEvent(message="invalid operator command").model_dump_json()
            )
            continue
        if command is None:
            continue
        try:
            if not await session.handle(command):
                return
        except (BrowserError, OperatorViolation) as exc:
            await websocket.send_text(OperatorErrorEvent(message=str(exc)).model_dump_json())


async def browser_operator_websocket(
    websocket: WebSocket,
    *,
    browser: OperatorBrowserRuntime,
    service_token: str,
) -> None:
    supplied = _bearer_token(websocket)
    if not supplied or not hmac.compare_digest(supplied, service_token):
        await websocket.close(code=4401)
        return
    await websocket.accept()
    events = BrowserOperatorEvents(browser, websocket)
    try:
        session = await OperatorSession.acquire(BrowserOperator(browser), events)
    except BrowserError as exc:
        await websocket.send_text(OperatorErrorEvent(message=str(exc)).model_dump_json())
        await websocket.close(code=4409)
        return
    try:
        await session.start()
        await _messages(websocket, session)
    except WebSocketDisconnect:
        pass
    finally:
        await session.close()
        with suppress(RuntimeError):
            await websocket.close()
