from __future__ import annotations

import logging

from briareus_oidc import TokenVerificationError
from fastmcp.server.auth import AccessToken, TokenVerifier

from .application.ports import PrincipalVerifier

logger = logging.getLogger(__name__)


class OidcMcpTokenVerifier(TokenVerifier):
    """An MCP resource server accepting externally verified OAuth access tokens."""

    def __init__(
        self,
        verifier: PrincipalVerifier,
        resource: str,
        *,
        service_id: str = "unknown",
    ) -> None:
        # Application role policy is configured independently of OAuth scopes.
        super().__init__(required_scopes=[])
        self.verifier = verifier
        self.resource = resource
        self.service_id = service_id

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            principal = await self.verifier.verify_async(token)
        except TokenVerificationError as exc:
            # Only a registered service ID and fixed reason category. No JWT claims,
            # bearer, client identifier or exception details go to observability.
            logger.info("mcp bearer rejected service=%s reason=%s", self.service_id, exc.reason)
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
