"""API authorization consumes Gateway-verified identity, not OIDC configuration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from briareus_oidc import VerifiedPrincipal


class PrincipalVerifier(Protocol):
    def verify(self, token: str) -> VerifiedPrincipal: ...
    async def verify_async(self, token: str) -> VerifiedPrincipal: ...


@dataclass(frozen=True)
class PanelTokenIdentity:
    verifier: PrincipalVerifier
    node_id: str

    def verify(self, token: str) -> VerifiedPrincipal:
        return self.verifier.verify(token)

    async def verify_async(self, token: str) -> VerifiedPrincipal:
        return await self.verifier.verify_async(token)
