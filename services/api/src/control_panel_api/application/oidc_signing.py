"""Verify provider identity before any independent Platform membership resolution."""

from typing import Protocol

from control_panel_api.application._constructor_bindings import _SignatureBinding
from control_panel_api.domain.native_login import SecretText
from control_panel_api.domain.oidc_identity import OidcIdentityRejected, VerifiedOidcIdentity
from control_panel_api.domain.oidc_signing import IdTokenIntent, OidcIdTokenClaims


class OidcIdSignature(Protocol):
    async def decode(self, raw: str, intent: IdTokenIntent) -> OidcIdTokenClaims: ...


class VerifyOidcIdToken(_SignatureBinding[OidcIdSignature]):
    async def execute(self, token: SecretText, intent: IdTokenIntent) -> VerifiedOidcIdentity:
        raw = token.get_secret_value()
        intent.require_token(raw)
        claims = await self._signature.decode(raw, intent)
        try:
            return claims.identity(intent)
        except (ValueError, TypeError, OverflowError) as exc:
            raise OidcIdentityRejected("Rauthy ID token invalid or expired") from exc
