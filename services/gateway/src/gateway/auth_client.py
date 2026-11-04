from __future__ import annotations

from briareus_zitadel_tokens import TokenVerificationError, ZitadelTokenVerifier
from fastmcp.server.auth import AccessToken, TokenVerifier


class ZitadelMcpTokenVerifier(TokenVerifier):
    """An MCP resource server accepting only external project-scoped ZITADEL JWTs."""

    def __init__(self, verifier: ZitadelTokenVerifier, resource: str) -> None:
        # ZITADEL JWT access tokens need not contain a scope claim. Project roles,
        # not an invented scope list or the requested URL, authorize each surface.
        super().__init__(required_scopes=[])
        self.verifier = verifier
        self.resource = resource

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            principal = await self.verifier.verify_async(token)
        except TokenVerificationError:
            return None
        return AccessToken(
            token=token,
            client_id=principal.client_id,
            subject=principal.subject,
            expires_at=principal.expires_at,
            scopes=list(principal.scopes),
            resource=self.resource,
            claims=principal.claims,
        )
