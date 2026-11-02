"""Compose pinned Rauthy reset/recovery inside the Control Panel browser boundary."""

import os
import secrets
import time

from fastapi import APIRouter

from control_panel_api._api_paths import AUTH_API_PREFIX
from control_panel_api._oidc import RauthyOidcAdapter
from control_panel_api._oidc_browser import OidcBrowserSessionStore
from control_panel_api._oidc_origin_policy import (
    PUBLIC_HOST,
    local_browser_host,
    resolve_browser_origin,
)
from control_panel_api._rauthy_native_init import PinnedNativeRauthyInit
from control_panel_api.application.password_setup import PasswordSetup
from control_panel_api.infrastructure.password_setup_provider import RauthyPasswordSetupProvider
from control_panel_api.infrastructure.password_setup_store import ValkeyPasswordSetupStore
from control_panel_api.presentation.password_setup_controller import PasswordSetupController
from control_panel_api.presentation.password_setup_models import EmptyRequest as EmptyRequest
from control_panel_api.presentation.password_setup_models import RecoveryRequest as RecoveryRequest
from control_panel_api.presentation.password_setup_models import SetupCode as SetupCode
from control_panel_api.presentation.password_setup_models import SetupPassword as SetupPassword


def _mail_ready() -> bool:
    return os.environ.get("RAUTHY_INVITATION_EMAIL_READY") == "1"


def _ticket() -> str:
    return secrets.token_urlsafe(32)


def password_setup_router(
    *,
    native: PinnedNativeRauthyInit,
    provider: RauthyOidcAdapter,
    sessions: OidcBrowserSessionStore,
    test_only_local_origin: str | None,
) -> APIRouter:
    origin = resolve_browser_origin(
        test_origin=test_only_local_origin,
        provider_issuer=provider.issuer,
        provider_client=provider.client_id,
    )
    setup = PasswordSetup(
        RauthyPasswordSetupProvider(native),
        ValkeyPasswordSetupStore(sessions.storage),
        mail_ready=_mail_ready,
        now=time.time,
        ticket=_ticket,
    )
    controller = PasswordSetupController(
        setup, origin=origin, host=local_browser_host(test_only_local_origin) or PUBLIC_HOST
    )
    router = APIRouter(prefix=AUTH_API_PREFIX + "/password-setup")
    router.add_api_route("/recovery-pow", controller.recovery_pow, methods=["POST"])
    router.add_api_route("/recovery-request", controller.recovery_request, methods=["POST"])
    router.add_api_route("/prepare", controller.prepare, methods=["POST"])
    router.add_api_route("/finish", controller.finish, methods=["POST"])
    return router
