"""Composition for pinned Rauthy rotation; refresh credentials never reach JS."""

from typing import TYPE_CHECKING

from pydantic import SecretStr

from control_panel_api.application.oidc_refresh import RefreshCredentialProof, RefreshOidcLogin
from control_panel_api.domain.oidc_identity import RefreshNotDispatched as RefreshNotDispatched
from control_panel_api.domain.oidc_identity import VerifiedOidcIdentity, VerifiedOidcLogin
from control_panel_api.domain.oidc_identity import (
    VerifiedRefreshCredential as VerifiedRefreshCredential,
)
from control_panel_api.domain.oidc_refresh import RefreshIntent
from control_panel_api.infrastructure.oidc_refresh import RauthyRefreshProvider

if TYPE_CHECKING:
    from control_panel_api._oidc import RauthyOidcAdapter, UnverifiedOidcTokenResponse


async def capture_refresh(
    provider: "RauthyOidcAdapter",
    tokens: "UnverifiedOidcTokenResponse",
    identity: VerifiedOidcIdentity,
) -> VerifiedRefreshCredential | None:
    if tokens.refresh_token is None:
        return None
    protocol = RauthyRefreshProvider(provider)
    endpoints = await protocol.endpoints()
    intent = RefreshIntent(
        identity.issuer, identity.client_id, identity.subject, provider.resource_audience
    )
    return await RefreshCredentialProof(protocol).capture(tokens.refresh_token, intent, endpoints)


async def refresh_login(
    provider: "RauthyOidcAdapter",
    *,
    token: SecretStr,
    subject: str,
) -> VerifiedOidcLogin:
    intent = RefreshIntent(provider.issuer, provider.client_id, subject, provider.resource_audience)
    return await RefreshOidcLogin(RauthyRefreshProvider(provider)).execute(token, intent)
