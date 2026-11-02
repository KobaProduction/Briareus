"""Private CDP framing and credential-protected lifecycle presentation."""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Literal, cast

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket

from common.browser_profile import DEFAULT_BROWSER_DESKTOP_PROFILE
from common.settings import BrowserSettings
from common.websocket_proxy import relay_websocket

from .application import BrowserLifecycle
from .configuration import BrowserLaunchSource
from .process import ChromiumProcess

_token = os.environ.get("BROWSER_CONTROL_TOKEN", "")
if not _token:
    raise ValueError("BROWSER_CONTROL_TOKEN is required")
_process = ChromiumProcess(BrowserLaunchSource(BrowserSettings(), DEFAULT_BROWSER_DESKTOP_PROFILE))
_lifecycle = BrowserLifecycle(_process)


@asynccontextmanager
async def lifespan(_app: Starlette) -> AsyncIterator[None]:
    await _process.start()
    supervisor = asyncio.create_task(_process.supervise())
    try:
        yield
    finally:
        supervisor.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await supervisor
        await _process.stop()


def authorized(request: Request) -> bool:
    supplied = request.headers.get("authorization", "")
    return hmac.compare_digest(supplied, f"Bearer {_token}")


async def control(request: Request) -> Response:
    if not authorized(request):
        return PlainTextResponse("Unauthorized", status_code=401)
    action = request.path_params["action"]
    if action == "state":
        return JSONResponse(asdict(_process.state()))
    if request.method != "POST" or action not in {"start", "stop", "restart"}:
        return PlainTextResponse("Not Found", status_code=404)
    state = await _lifecycle.execute(cast(Literal["start", "stop", "restart"], action))
    return JSONResponse(asdict(state))


async def health(_request: Request) -> Response:
    state = _process.state()
    return JSONResponse(asdict(state), status_code=200 if state.running else 503)


async def cdp_http(request: Request) -> Response:
    path = request.path_params["path"]
    target = f"http://127.0.0.1:9224/{path}"
    if request.url.query:
        target += "?" + request.url.query
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            upstream = await client.request(request.method, target)
    except httpx.RequestError:
        return PlainTextResponse("Chromium is unavailable", status_code=503)
    body = upstream.content.replace(b"127.0.0.1:9224", str(request.url.netloc).encode())
    return Response(
        body, status_code=upstream.status_code, media_type=upstream.headers.get("content-type")
    )


async def cdp_websocket(websocket: WebSocket) -> None:
    path = websocket.path_params["path"]
    await relay_websocket(websocket, f"ws://127.0.0.1:9224/{path}", origin=None)


app = Starlette(
    lifespan=lifespan,
    routes=[
        Route("/health", health),
        Route("/control/{action}", control, methods=["GET", "POST"]),
        Route("/{path:path}", cdp_http, methods=["GET", "PUT", "POST", "DELETE"]),
        WebSocketRoute("/{path:path}", cdp_websocket),
    ],
)
