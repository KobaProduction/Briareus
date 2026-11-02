"""Bind coarse Access grants to the independently verified provider subject."""

from authorization._decision_api import (
    AuthorizationDecisionReader,
    DecisionCommand,
    VerifiedDecisionCaller,
)
from authorization.domain.decisions import AuthorizedCurrentGrant
from authorization.domain.workspace_effects import WorkspaceIdentity


class SqlMcpAdmissionGrant:
    def __init__(self, reader: AuthorizationDecisionReader, command: DecisionCommand) -> None:
        self.reader = reader
        self.command = command

    async def current(self, identity: WorkspaceIdentity) -> AuthorizedCurrentGrant | None:
        command = self.command
        caller = VerifiedDecisionCaller(
            actor_uuid=identity.actor_uuid,
            project_uuid=command.project_uuid,
            agent_session_uuid=command.agent_session_uuid,
            consumer="gateway",
            authority="rauthy",
            verified_peer_audience="briareus:access",
            proof_expires_at=min(identity.actor_expires_at, identity.provider_expires_at),
            attested_effect_key=None,
        )
        return await self.reader.current_grant(command, caller)
