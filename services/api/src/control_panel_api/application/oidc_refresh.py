"""One rotating provider effect, followed by independent identity and resource proofs."""

from dataclasses import replace
from typing import Protocol

from control_panel_api.application._constructor_bindings import _SignatureBinding
from control_panel_api.application.oidc_provider_contracts import UnverifiedOidcTokenResponse
from control_panel_api.domain.native_login import SecretText
from control_panel_api.domain.oidc_identity import (
    OidcIdentityKeysUnavailable,
    OidcProviderUnavailable,
    PrivateOidcResourceCredential,
    VerifiedOidcIdentity,
    VerifiedOidcLogin,
    VerifiedRefreshCredential,
)
from control_panel_api.domain.oidc_refresh import (
    RefreshClaims,
    RefreshedIdClaims,
    RefreshEndpoints,
    RefreshIntent,
)


class RefreshCredentialSignature(Protocol):
    async def refresh_claims(
        self, token: SecretText, intent: RefreshIntent, endpoints: RefreshEndpoints
    ) -> RefreshClaims: ...


class RefreshProvider(RefreshCredentialSignature, Protocol):
    async def rotation_endpoints(self) -> RefreshEndpoints: ...

    async def rotate(
        self, token: SecretText, endpoints: RefreshEndpoints
    ) -> UnverifiedOidcTokenResponse: ...

    async def identity_claims(
        self, token: SecretText, intent: RefreshIntent, endpoints: RefreshEndpoints
    ) -> RefreshedIdClaims: ...

    async def current_userinfo(
        self, tokens: UnverifiedOidcTokenResponse, identity: VerifiedOidcIdentity
    ) -> None: ...

    async def resource(
        self,
        tokens: UnverifiedOidcTokenResponse,
        identity: VerifiedOidcIdentity,
        audience: str,
        endpoints: RefreshEndpoints,
    ) -> PrivateOidcResourceCredential: ...


class RefreshCredentialProof(_SignatureBinding[RefreshCredentialSignature]):
    """Shared signature/purpose collaborator for code exchange and token rotation."""

    async def capture(
        self, token: SecretText | None, intent: RefreshIntent, endpoints: RefreshEndpoints
    ) -> VerifiedRefreshCredential | None:
        if token is None:
            return None
        claims = await self._signature.refresh_claims(token, intent, endpoints)
        return claims.credential(token, intent)


class RefreshOidcLogin:
    def __init__(self, provider: RefreshProvider) -> None:
        self._provider = provider
        self._renewal = RefreshCredentialProof(provider)

    async def execute(self, token: SecretText, intent: RefreshIntent) -> VerifiedOidcLogin:
        endpoints = await self._provider.rotation_endpoints()
        # Discovery pins the provider's exact issuer spelling. Configuration may
        # omit its trailing slash, but signed identity/resource/refresh proofs may not.
        intent = replace(intent, issuer=endpoints.issuer)
        tokens = await self._provider.rotate(token, endpoints)
        try:
            claims = await self._provider.identity_claims(tokens.id_token, intent, endpoints)
            identity = claims.identity(intent, tokens.deadline)
            await self._provider.current_userinfo(tokens, identity)
            resource = None
            if intent.resource_audience is not None:
                resource = await self._provider.resource(
                    tokens, identity, intent.resource_audience, endpoints
                )
                identity = replace(
                    identity, expires_at=min(identity.expires_at, resource.expires_at)
                )
            renewal = await self._renewal.capture(tokens.refresh_token, intent, endpoints)
        except OidcIdentityKeysUnavailable:
            # Rotation may already have consumed the credential; retain the attempt marker.
            raise OidcProviderUnavailable("Renewal signing authority unavailable") from None
        return VerifiedOidcLogin(identity, resource, renewal)
