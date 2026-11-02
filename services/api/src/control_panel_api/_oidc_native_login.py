"""Composition root for native first factor and provider-owned MFA."""

from fastapi import APIRouter

from ._api_paths import AUTH_API_PREFIX
from ._oidc import RauthyOidcAdapter
from ._oidc_browser import OidcBrowserSessionStore
from ._oidc_origin_policy import (
    BROWSER_ORIGIN,
    PUBLIC_HOST,
    browser_callback_uri,
    local_browser_host,
    resolve_browser_origin,
)
from ._rauthy_native_init import PinnedNativeRauthyInit
from .application.native_login import NativeLogin
from .infrastructure.native_login import ProviderNativeLogin
from .presentation.native_login_controller import (
    NativeLoginController,
)
from .presentation.native_login_controller import (
    NativeOtpFinishRequest as NativeOtpFinishRequest,
)
from .presentation.native_login_controller import (
    NativeOtpMethodRequest as NativeOtpMethodRequest,
)


def native_login_router(
    *,
    provider: RauthyOidcAdapter,
    transactions: OidcBrowserSessionStore,
    native_provider: PinnedNativeRauthyInit,
    test_only_local_origin: str | None,
) -> APIRouter:
    origin = resolve_browser_origin(
        test_origin=test_only_local_origin,
        provider_issuer=provider.issuer,
        provider_client=provider.client_id,
    )
    if (
        native_provider.issuer != provider.issuer
        or native_provider.client_id != provider.client_id
        or native_provider.callback != browser_callback_uri(origin)
        or (test_only_local_origin is None and origin != BROWSER_ORIGIN)
    ):
        raise ValueError("native credentials require one fixed matching issuer/client/callback")
    gateway = ProviderNativeLogin(
        provider, transactions, native_provider, callback=browser_callback_uri(origin)
    )
    controller = NativeLoginController(
        NativeLogin(gateway, resource_audience=provider.resource_audience),
        origin=origin,
        host=local_browser_host(test_only_local_origin) or PUBLIC_HOST,
    )
    router = APIRouter()
    router.add_api_route(
        AUTH_API_PREFIX + "/capabilities", controller.capabilities, methods=["GET"]
    )
    router.add_api_route(AUTH_API_PREFIX + "/cancel", controller.cancel, methods=["POST"])
    router.add_api_route(
        AUTH_API_PREFIX + "/first-factor", controller.first_factor, methods=["POST"]
    )
    router.add_api_route(AUTH_API_PREFIX + "/otp/start", controller.otp_start, methods=["POST"])
    router.add_api_route(AUTH_API_PREFIX + "/otp/finish", controller.otp_finish, methods=["POST"])
    return router
