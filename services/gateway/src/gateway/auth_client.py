from __future__ import annotations

from briareus_oidc import OidcTokenVerifier, TokenVerificationError
from fastmcp.server.auth import AccessToken, TokenVerifier


class OidcMcpTokenVerifier(TokenVerifier):
    """An MCP resource server accepting only external OIDC access JWTs."""

    def __init__(self, verifier: OidcTokenVerifier, resource: str) -> None:
        # Application role policy is configured independently of OAuth scopes.
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
