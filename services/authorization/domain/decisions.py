"""Request-bound current grant scope; an AgentSession UUID is not identity."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from authorization.domain.resource_scopes import HandName


class DecisionAuthenticationRequired(Exception):
    """The calling service or its delegated Rauthy subject was not verified."""


class DecisionScopeDenied(Exception):
    """A verified caller is not authorized for this Project/AgentSession."""


class DecisionAuthorityUnavailable(Exception):
    """Verified Rauthy, peer or Project current-state authority is unavailable."""


@dataclass(frozen=True, slots=True)
class DecisionEffect:
    hand: HandName
    tool: str
    resource_kind: str
    resource_id: str
    effect_key: str


@dataclass(frozen=True, slots=True)
class DecisionScope:
    project_uuid: UUID
    agent_session_uuid: UUID
    action: str
    expected_grant_revision: int
    effect: DecisionEffect | None


@dataclass(frozen=True, slots=True)
class VerifiedDecisionCaller:
    actor_uuid: UUID
    project_uuid: UUID
    agent_session_uuid: UUID
    consumer: Literal["gateway", "hand"]
    authority: str
    verified_peer_audience: str
    proof_expires_at: datetime
    attested_effect_key: str | None = None

    def matches(self, scope: DecisionScope, now: datetime) -> bool:
        identity_matches = (
            self.actor_uuid.version == 4
            and self.project_uuid == scope.project_uuid
            and self.agent_session_uuid == scope.agent_session_uuid
        )
        authority_matches = (
            self.authority == "rauthy"
            and self.consumer in {"gateway", "hand"}
            and self.verified_peer_audience == "briareus:access"
            and self.proof_expires_at.tzinfo is not None
            and self.proof_expires_at > now
        )
        expected_consumer = "gateway" if scope.action == "mcp.connect" else "hand"
        expected_key = scope.effect.effect_key if scope.effect is not None else None
        return (
            identity_matches
            and authority_matches
            and self.consumer == expected_consumer
            and self.attested_effect_key == expected_key
        )


@dataclass(frozen=True, slots=True)
class AuthorizedCurrentGrant:
    actor_uuid: UUID
    project_uuid: UUID
    agent_session_uuid: UUID
    grant_revision: int
    expires_at: datetime
