"""Complete one consumed original PKCE intent using independent provider proofs."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from control_panel_api.application.oidc_provider_contracts import UnverifiedOidcTokenResponse
from control_panel_api.domain.native_login import SecretText
from control_panel_api.domain.oidc_identity import (
    OidcIdentityRejected,
    PrivateOidcResourceCredential,
    VerifiedOidcIdentity,
    VerifiedOidcLogin,
    VerifiedRefreshCredential,
)
from control_panel_api.domain.oidc_provider import bounded_identity, require_original_intent


@dataclass(frozen=True, slots=True)
class CompleteOidcCode:
    code: str = field(repr=False)
    redirect_uri: str
    verifier: SecretText = field(repr=False)
    nonce: str = field(repr=False)
    issuer: str
    resource_audience: str | None


class OidcCodeProvider(Protocol):
    @property
    def issuer(self) -> str: ...
    @property
    def resource_audience(self) -> str | None: ...
    async def exchange_authorization_code(
        self,
        *,
        code: str,
        redirect_uri: str,
        code_verifier: SecretText,
        resource_audience: str | None = None,
    ) -> UnverifiedOidcTokenResponse: ...
    async def verify_exchanged_id_token(
        self,
        *,
        tokens: UnverifiedOidcTokenResponse,
        expected_nonce: str,
    ) -> VerifiedOidcIdentity: ...
    async def verify_current_userinfo(
        self,
        *,
        tokens: UnverifiedOidcTokenResponse,
        identity: VerifiedOidcIdentity,
    ) -> None: ...
    async def verify_resource(
        self,
        tokens: UnverifiedOidcTokenResponse,
        identity: VerifiedOidcIdentity,
        audience: str,
    ) -> PrivateOidcResourceCredential: ...
    async def capture_refresh(
        self,
        tokens: UnverifiedOidcTokenResponse,
        identity: VerifiedOidcIdentity,
    ) -> VerifiedRefreshCredential | None: ...


class AuthenticateOidcCode:
    def __init__(self, provider: OidcCodeProvider, now: Callable[[], datetime]) -> None:
        self._provider, self._now = provider, now

    async def execute(self, command: CompleteOidcCode) -> VerifiedOidcLogin:
        provider = self._provider
        require_original_intent(
            expected_issuer=command.issuer,
            issuer=provider.issuer,
            expected_resource=command.resource_audience,
            resource_audience=provider.resource_audience,
        )
        tokens = await provider.exchange_authorization_code(
            code=command.code,
            redirect_uri=command.redirect_uri,
            code_verifier=command.verifier,
            resource_audience=command.resource_audience,
        )
        identity = await provider.verify_exchanged_id_token(
            tokens=tokens, expected_nonce=command.nonce
        )
        if identity.issuer != command.issuer:
            raise OidcIdentityRejected("callback issuer does not match signed issuer")
        await provider.verify_current_userinfo(tokens=tokens, identity=identity)
        identity = bounded_identity(identity, tokens.deadline)
        resource = None
        if command.resource_audience is not None:
            resource = await provider.verify_resource(tokens, identity, command.resource_audience)
            identity = bounded_identity(identity, resource.expires_at)
        if identity.expires_at <= self._now():
            raise OidcIdentityRejected("OAuth identity expired before private session creation")
        refresh = await provider.capture_refresh(tokens, identity)
        return VerifiedOidcLogin(identity, resource, refresh)
