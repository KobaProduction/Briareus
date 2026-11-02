"""Composition root for native login initialization and one-use provider PoW."""

from fastapi import APIRouter

from ._api_paths import AUTH_API_PREFIX
from ._oidc import RauthyOidcAdapter
from ._oidc_browser import OidcBrowserSessionStore
from ._oidc_origin_policy import (
    PUBLIC_HOST,
    browser_callback_uri,
    local_browser_host,
    resolve_browser_origin,
)
from ._rauthy_native_init import PinnedNativeRauthyInit
from .application.native_login_start import NativeLoginStart
from .infrastructure.native_login import ProviderNativeLogin
from .presentation.native_login_start import (
    NativeStartController,
)
from .presentation.native_login_start import (
    _exact_empty_native_request as _exact_empty_native_request,
)


def native_login_start_router(
    *,
    provider: RauthyOidcAdapter,
    transactions: OidcBrowserSessionStore,
    native_init: PinnedNativeRauthyInit,
    test_only_local_origin: str | None,
) -> APIRouter:
    origin = resolve_browser_origin(
        test_origin=test_only_local_origin,
        provider_issuer=provider.issuer,
        provider_client=provider.client_id,
    )
    if (
        native_init.issuer != provider.issuer
        or native_init.client_id != provider.client_id
        or native_init.callback != browser_callback_uri(origin)
    ):
        raise ValueError("native Rauthy issuer/client/callback differs from signed OAuth provider")
    gateway = ProviderNativeLogin(
        provider, transactions, native_init, callback=browser_callback_uri(origin)
    )
    controller = NativeStartController(
        NativeLoginStart(gateway),
        origin=origin,
        host=local_browser_host(test_only_local_origin) or PUBLIC_HOST,
    )
    router = APIRouter()
    router.add_api_route(AUTH_API_PREFIX + "/start", controller.start, methods=["POST"])
    router.add_api_route(AUTH_API_PREFIX + "/pow", controller.issue_pow, methods=["POST"])
    return router
