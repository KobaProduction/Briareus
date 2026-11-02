"""Bounded pre-auth request parsing and response/cookie presentation."""

import asyncio

from fastapi import Request
from fastapi.responses import Response
from starlette.requests import ClientDisconnect

from control_panel_api._oidc_browser import _NATIVE_TX_COOKIE, _strict_browser_cookies
from control_panel_api.application.native_login_start import NativeLoginStart

from ._bindings import _NativeControllerBinding
from .native_login import native_login_response
from .native_login_controller import _failure


async def _exact_empty_native_request(request: Request, *, origin: str, host: str) -> bool:
    """Bound pre-auth body reception without Request.body() buffering.

    Content-Length is a claim, never a safe receive limit. A forged length
    of 2 with a large ASGI body must deny before buffering the payload.
    """
    if (
        request.headers.getlist("origin") != [origin]
        or request.headers.getlist("host") != [host]
        or request.headers.getlist("content-type") != ["application/json"]
        or request.headers.getlist("content-length") != ["2"]
        or request.headers.getlist("transfer-encoding")
        or request.headers.getlist("authorization")
        or len(request.headers.getlist("cookie")) > 1
        or request.query_params
    ):
        return False
    result = bytearray()
    try:
        async with asyncio.timeout(5):
            async for part in request.stream():
                if len(part) > 2 - len(result):
                    return False
                result.extend(part)
    except (TimeoutError, RuntimeError, ClientDisconnect):
        return False
    return result == b"{}"


class NativeStartController(_NativeControllerBinding[NativeLoginStart]):
    async def start(self, request: Request) -> Response:
        if not await _exact_empty_native_request(request, origin=self._origin, host=self._host):
            return _failure(403, "NATIVE_ORIGIN_OR_REQUEST_DENIED")
        handles = _strict_browser_cookies(request)
        if handles is None:
            return _failure(401, "NATIVE_COOKIE_INVALID")
        result = await self._login.start(handles.get(_NATIVE_TX_COOKIE))
        return native_login_response(result)

    async def issue_pow(self, request: Request) -> Response:
        if not await _exact_empty_native_request(request, origin=self._origin, host=self._host):
            return _failure(403, "NATIVE_ORIGIN_OR_REQUEST_DENIED")
        handles = _strict_browser_cookies(request)
        pending = handles.get(_NATIVE_TX_COOKIE) if handles is not None else None
        if pending is None:
            return _failure(401, "NATIVE_INIT_REQUIRED")
        return native_login_response(await self._login.issue_pow(pending))
