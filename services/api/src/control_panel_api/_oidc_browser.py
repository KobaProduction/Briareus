"""Browser OIDC code+PKCE with single-use private Valkey transactions.

Neither Rauthy OAuth identity nor this short-lived browser session is a
Briareus Platform User, Project membership or Authorization/Cedar grant.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import overload

from fastapi import APIRouter
from fastapi.responses import Response
from starlette.requests import HTTPConnection

from ._api_paths import AUTH_API_PREFIX, REGISTERED_RAUTHY_CALLBACK_PATH
from ._oidc import RauthyOidcAdapter
from ._oidc_origin_policy import (
    browser_callback_uri,
    local_browser_host,
    resolve_browser_origin,
)
from .domain.native_login import PrivateNativeOtpPending as PrivateNativeOtpPending
from .domain.native_login import PrivateNativePending as PrivateNativePending
from .domain.oidc_identity import OidcSessionStoreUnavailable as OidcSessionStoreUnavailable
from .domain.oidc_identity import PrivateOidcPending as PrivateOidcPending
from .domain.platform_authority import PanelOidcSession as PanelOidcSession
from .infrastructure.browser_store import OidcBrowserSessionStore as OidcBrowserSessionStore

_TX_COOKIE = "__Host-briareus_oidc_transaction"
_NATIVE_TX_COOKIE = "__Host-briareus_native_transaction"
_SID_COOKIE = "__Host-briareus_oidc_session"
_SETUP_COOKIE = "__Host-briareus_password_setup"
_MAX_IDENTITY_SECONDS = 900
_MAX_TRANSACTION_SECONDS = 300
_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}
_TOKEN = re.compile(r"[A-Za-z0-9_-]{32,128}")
_PANEL_HANDLES = frozenset({_TX_COOKIE, _NATIVE_TX_COOKIE, _SID_COOKIE, _SETUP_COOKIE})


@dataclass(frozen=True, slots=True)
class BrowserCookies:
    transaction: str | None = None
    native_transaction: str | None = None
    session: str | None = None
    password_setup: str | None = None

    def __bool__(self) -> bool:
        return any((self.transaction, self.native_transaction, self.session, self.password_setup))

    @overload
    def get(self, name: str) -> str | None: ...

    @overload
    def get(self, name: str, default: str) -> str: ...

    def get(self, name: str, default: str | None = None) -> str | None:
        if name == _TX_COOKIE:
            value = self.transaction
        elif name == _NATIVE_TX_COOKIE:
            value = self.native_transaction
        elif name == _SID_COOKIE:
            value = self.session
        elif name == _SETUP_COOKIE:
            value = self.password_setup
        else:
            value = None
        return default if value is None else value


def _strict_browser_cookies(request: HTTPConnection) -> BrowserCookies | None:
    """Read a SINGLE, unambiguous browser Cookie header for Panel state.

    Starlette's request.cookies silently picks a value from duplicate cookie
    names; that can make a cancelled/logout session appear current to another
    route. All three Panel handles are generated as unquoted opaque tokens.
    Return None for ambiguity, not a guessed cookie or empty authenticated
    state. Other application cookies are ignored, never made authoritative.
    """
    raw = request.headers.getlist("cookie")
    if len(raw) > 1 or (raw and len(raw[0]) > 8192):
        return None
    if not raw:
        return BrowserCookies()
    result: dict[str, str] = {}
    for entry in raw[0].split(";"):
        name, separator, value = entry.strip().partition("=")
        if name not in _PANEL_HANDLES:
            continue
        if not separator or name in result or _TOKEN.fullmatch(value) is None:
            return None
        result[name] = value
    return BrowserCookies(
        result.get(_TX_COOKIE),
        result.get(_NATIVE_TX_COOKIE),
        result.get(_SID_COOKIE),
        result.get(_SETUP_COOKIE),
    )


def _cookie(response: Response, name: str, value: str, max_age: int) -> None:
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        secure=True,
        httponly=True,
        samesite="lax",
        path="/",
    )


def _clear(response: Response, name: str) -> None:
    response.delete_cookie(name, path="/", secure=True, httponly=True, samesite="lax")


def oidc_browser_router(
    provider: RauthyOidcAdapter,
    sessions: OidcBrowserSessionStore,
    *,
    test_only_local_origin: str | None = None,
) -> APIRouter:
    from .application.browser_identity import BrowserIdentity
    from .infrastructure.browser_identity import ProviderBrowserIdentity
    from .presentation.browser_identity import BrowserIdentityController

    origin = resolve_browser_origin(
        test_origin=test_only_local_origin,
        provider_issuer=provider.issuer,
        provider_client=provider.client_id,
    )
    port = ProviderBrowserIdentity(provider, sessions, callback=browser_callback_uri(origin))
    controller = BrowserIdentityController(
        BrowserIdentity(port, issuer=provider.issuer, client_id=provider.client_id),
        origin=origin,
        host=local_browser_host(test_only_local_origin),
    )
    router = APIRouter()
    router.add_api_route(AUTH_API_PREFIX + "/authorize", controller.start, methods=["GET"])
    router.add_api_route(REGISTERED_RAUTHY_CALLBACK_PATH, controller.callback, methods=["GET"])
    router.add_api_route(AUTH_API_PREFIX + "/session", controller.current, methods=["GET"])
    router.add_api_route(AUTH_API_PREFIX + "/logout", controller.logout, methods=["POST"])
    return router
