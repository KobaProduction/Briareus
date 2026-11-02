"""Translate trusted SQL/Cedar and Files-owner evidence to read authority."""

from datetime import UTC, datetime

from authorization._decision_api import (
    AuthorizationDecisionReader,
    AuthorizedCurrentGrant,
    DecisionCommand,
    VerifiedDecisionCaller,
)
from authorization._resource_scope import TrustedResourceOwnerPort, matches_current_owner
from authorization.domain.files_read import (
    ReadAuthorityUnavailable,
    ReadCaller,
    ReadGrant,
    ReadResource,
    ReadScopeDenied,
)
from authorization.domain.sessions import SessionResourceGrant
from common.platform_ids import PlatformProjectId


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


def read_caller(caller: VerifiedDecisionCaller) -> ReadCaller:
    return ReadCaller(
        actor_uuid=caller.actor_uuid,
        project_uuid=caller.project_uuid,
        agent_session_uuid=caller.agent_session_uuid,
        consumer=caller.consumer,
        authority=caller.authority,
        peer_audience=caller.verified_peer_audience,
        effect_key=caller.attested_effect_key,
        expires_at=caller.proof_expires_at,
    )


class CurrentReadAuthorities:
    def __init__(
        self,
        command: DecisionCommand,
        caller: VerifiedDecisionCaller,
        reader: AuthorizationDecisionReader,
        owner: TrustedResourceOwnerPort,
    ) -> None:
        self._command = command
        self._caller = caller
        self._reader = reader
        self._owner = owner

    def current_resource(self) -> ReadResource:
        command = self._command
        if command.resource is None:
            raise ReadScopeDenied("Files resource missing")
        if command.hand is None or command.tool is None:
            raise ReadAuthorityUnavailable("Files resource owner proof absent")
        scope = SessionResourceGrant(
            command.hand, command.tool, command.action, command.resource.kind, command.resource.id
        )
        try:
            proof = self._owner.verify_current_scope(
                project_uuid=PlatformProjectId(command.project_uuid), scope=scope
            )
        except Exception:
            raise ReadAuthorityUnavailable("Files resource owner unavailable") from None
        if proof is None:
            raise ReadAuthorityUnavailable("Files resource owner proof absent")
        if not matches_current_owner(
            proof, project_uuid=PlatformProjectId(command.project_uuid), scope=scope
        ):
            raise ReadScopeDenied("Files resource scope or revision changed")
        return ReadResource(proof.revision, proof.expires_at)

    async def current_grant(self) -> ReadGrant:
        grant = await self._reader.current_grant(self._command, self._caller)
        if not isinstance(grant, AuthorizedCurrentGrant):
            raise ReadScopeDenied("Files read current Access grant denied")
        return ReadGrant(
            grant.actor_uuid,
            grant.project_uuid,
            grant.agent_session_uuid,
            grant.grant_revision,
            grant.expires_at,
        )
