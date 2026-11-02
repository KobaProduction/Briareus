"""Coarse MCP connection admission never substitutes for exact Hand effects."""

from datetime import UTC, datetime
from typing import Protocol

from authorization.application.workspace_effects import WorkspaceIdentityPort
from authorization.domain.decisions import AuthorizedCurrentGrant
from authorization.domain.mcp_identity import McpAuthorityExpired, McpGrantDenied
from authorization.domain.workspace_effects import WorkspaceIdentity


class McpAdmissionGrantPort(Protocol):
    async def current(self, identity: WorkspaceIdentity) -> AuthorizedCurrentGrant | None: ...


class AdmitMcpConnection:
    def __init__(self, identities: WorkspaceIdentityPort, grants: McpAdmissionGrantPort) -> None:
        self.identities = identities
        self.grants = grants

    async def execute(self) -> None:
        identity = await self.identities.current()
        current = await self.grants.current(identity)
        if current is None:
            raise McpGrantDenied
        if current.expires_at <= datetime.now(UTC):
            raise McpAuthorityExpired
