"""Verify a provider resource bearer without turning it into a local grant."""

from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from control_panel_api.domain.native_login import SecretText
from control_panel_api.domain.oidc_identity import (
    OidcIdentityRejected,
    PrivateOidcResourceCredential,
)
from control_panel_api.domain.oidc_signing_resource import OidcResourceClaims, ResourceTokenIntent


class OidcResourceSignature(Protocol):
    async def decode(self, raw: str, intent: ResourceTokenIntent) -> OidcResourceClaims: ...


class VerifyOidcResource:
    def __init__(self, signature: OidcResourceSignature, now: Callable[[], datetime]) -> None:
        self._signature, self._now = signature, now

    async def execute(
        self,
        token: SecretText,
        intent: ResourceTokenIntent,
    ) -> PrivateOidcResourceCredential:
        claims = await self._signature.decode(token.get_secret_value(), intent)
        try:
            return claims.credential(intent, token, self._now)
        except (TypeError, ValueError, OverflowError):
            raise OidcIdentityRejected("Rauthy resource bearer rejected") from None
