"""Existing OIDC HTTP contracts with bounded callback and cookie validation."""

import hmac
from dataclasses import dataclass

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from control_panel_api._oidc_browser import (
    _MAX_TRANSACTION_SECONDS,
    _NATIVE_TX_COOKIE,
    _SID_COOKIE,
    _TOKEN,
    _TX_COOKIE,
    _clear,
    _cookie,
    _strict_browser_cookies,
)
from control_panel_api.application.browser_identity import BrowserIdentity, BrowserIdentityFailure

HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


@dataclass(frozen=True, slots=True)
class AuthorizationCodeQuery:
    state: str
    code: str
    issuer: str


def callback_query(request: Request) -> AuthorizationCodeQuery:
    args = request.query_params
    states, codes, issuers = args.getlist("state"), args.getlist("code"), args.getlist("iss")
    if (
        set(args) != {"state", "code", "iss"}
        or len(states) != 1
        or len(codes) != 1
        or len(issuers) != 1
        or not 12 <= len(issuers[0]) <= 512
        or any(ch.isspace() for ch in issuers[0])
        or _TOKEN.fullmatch(states[0]) is None
        or not 1 <= len(codes[0]) <= 4096
        or any(ch.isspace() for ch in codes[0])
    ):
        raise HTTPException(400, detail="invalid OIDC authorization callback")
    cookies = _strict_browser_cookies(request)
    original = cookies.get(_TX_COOKIE, "") if cookies is not None else ""
    if _TOKEN.fullmatch(original) is None or not hmac.compare_digest(original, states[0]):
        raise HTTPException(401, detail="OIDC state mismatch")
    return AuthorizationCodeQuery(states[0], codes[0], issuers[0])


def session_failure(failure: BrowserIdentityFailure) -> JSONResponse:
    response = JSONResponse(
        {"error": {"code": failure.code}},
        status_code=failure.status,
        headers=HEADERS,
    )
    if failure.clear_cookie:
        _clear(response, _SID_COOKIE)
    return response


class BrowserIdentityController:
    def __init__(self, identity: BrowserIdentity, *, origin: str, host: str | None) -> None:
        self._identity = identity
        self._origin = origin
        self._host = host

    def _enforce_host(self, request: Request) -> None:
        if self._host is not None and request.headers.getlist("host") != [self._host]:
            raise HTTPException(403, detail="local OIDC browser host mismatch")

    async def start(self, request: Request) -> Response:
        self._enforce_host(request)
        result = await self._identity.start()
        if isinstance(result, BrowserIdentityFailure):
            raise HTTPException(result.status, detail=result.detail)
        response = RedirectResponse(result.authorization_url, status_code=302, headers=HEADERS)
        _cookie(response, _TX_COOKIE, result.state, _MAX_TRANSACTION_SECONDS)
        return response

    async def callback(self, request: Request) -> Response:
        self._enforce_host(request)
        query = callback_query(request)
        result = await self._identity.callback(query.state, query.code, query.issuer)
        if isinstance(result, BrowserIdentityFailure):
            raise HTTPException(result.status, detail=result.detail)
        response = RedirectResponse(self._origin + "/panel/", status_code=303, headers=HEADERS)
        _clear(response, _TX_COOKIE)
        _cookie(response, _SID_COOKIE, result.ticket, result.seconds)
        return response

    async def current(self, request: Request) -> Response:
        if self._host is not None and request.headers.getlist("host") != [self._host]:
            return session_failure(BrowserIdentityFailure(403, code="OIDC_BROWSER_HOST_MISMATCH"))
        cookies = _strict_browser_cookies(request)
        ticket = cookies.get(_SID_COOKIE, "") if cookies is not None else ""
        if _TOKEN.fullmatch(ticket) is None:
            return session_failure(BrowserIdentityFailure(401, code="OIDC_SESSION_REQUIRED"))
        result = await self._identity.current(ticket)
        if isinstance(result, BrowserIdentityFailure):
            return session_failure(result)
        identity = result.identity
        response = JSONResponse(
            {
                "authenticated": True,
                "authority": "rauthy",
                "subject": identity.subject,
                "issuer": identity.issuer,
                "client_id": identity.client_id,
                "expires_at": identity.expires_at.isoformat(),
                "platform_membership_verified": False,
                "permissions": [],
            },
            headers=HEADERS,
        )
        if result.renewed_seconds is not None:
            _cookie(response, _SID_COOKIE, ticket, result.renewed_seconds)
        return response

    async def logout(self, request: Request) -> Response:
        self._enforce_host(request)
        if request.headers.getlist("origin") != [self._origin]:
            raise HTTPException(403, detail="same-origin logout required")
        cookies = _strict_browser_cookies(request)
        if cookies is None:
            raise HTTPException(401, detail="ambiguous OIDC browser cookies")
        ticket, state = cookies.get(_SID_COOKIE, ""), cookies.get(_NATIVE_TX_COOKIE, "")
        failure = await self._identity.logout(
            ticket if _TOKEN.fullmatch(ticket) else None,
            state if _TOKEN.fullmatch(state) else None,
        )
        if failure is not None:
            raise HTTPException(failure.status, detail=failure.detail)
        response = Response(status_code=204, headers=HEADERS)
        for cookie in (_SID_COOKIE, _TX_COOKIE, _NATIVE_TX_COOKIE):
            _clear(response, cookie)
        return response
