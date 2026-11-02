"""Composition for revocable per-MCP credentials in the browser escrow."""

from control_panel_api._oidc import RauthyOidcAdapter
from control_panel_api._oidc_browser import OidcBrowserSessionStore
from control_panel_api._oidc_origin_policy import MCP_HANDS, mcp_resource_audience
from control_panel_api._resource_broker import ResourceTokenBroker
from control_panel_api.application.resource_escrow import (
    ResolveResourceCredential,
    ResourceSelection,
)
from control_panel_api.domain.oidc_identity import PrivateOidcResourceCredential
from control_panel_api.infrastructure.resource_escrow import ValkeyResourceSessions


class SessionResourceCredentials:
    def __init__(
        self,
        *,
        sessions: OidcBrowserSessionStore,
        provider: RauthyOidcAdapter,
        broker: ResourceTokenBroker | None = None,
    ) -> None:
        self.sessions, self.provider, self.broker = sessions, provider, broker
        self._service = ResolveResourceCredential(
            ValkeyResourceSessions(sessions, provider, sessions.storage), broker
        )

    async def resolve(self, ticket: str, hand: str) -> PrivateOidcResourceCredential | None:
        issuer, client_id = self.provider.issuer, self.provider.client_id
        selection = ResourceSelection(
            hand,
            mcp_resource_audience(issuer=issuer, client_id=client_id, hand=hand),
            mcp_resource_audience(issuer=issuer, client_id=client_id, hand="files"),
            frozenset(
                mcp_resource_audience(issuer=issuer, client_id=client_id, hand=item)
                for item in MCP_HANDS - {"files"}
            ),
        )
        return await self._service.execute(ticket, selection)
