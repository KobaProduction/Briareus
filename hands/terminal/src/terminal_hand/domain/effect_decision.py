"""Signed effect facts bind one current Terminal action and session lease."""

from dataclasses import dataclass
from uuid import UUID

from runtime_peer.domain.private_effect import PrivateEffectFacts


@dataclass(frozen=True)
class OperationPrincipal:
    actor_uuid: UUID
    session_uuid: UUID
    operation_uuid: UUID


@dataclass(frozen=True)
class EffectBinding:
    project_uuid: UUID
    resource_id: str
    resource_revision: int
    tool: str
    arguments_digest: str
    tools: frozenset[str]


@dataclass(frozen=True)
class TerminalDecision:
    facts: PrivateEffectFacts

    @property
    def principal(self) -> OperationPrincipal:
        return OperationPrincipal(
            self.facts.actor_uuid,
            self.facts.session_uuid,
            self.facts.operation_uuid,
        )

    @property
    def lease_identity(self) -> tuple[str, str, int]:
        return (
            str(self.facts.actor_uuid),
            str(self.facts.session_uuid),
            self.facts.grant_revision,
        )

    def require_binding(self, effect: EffectBinding) -> None:
        facts = self.facts
        if (
            not 0 < facts.expires_at - facts.issued_at <= 5
            or facts.not_before != facts.issued_at
            or facts.project_uuid != effect.project_uuid
            or facts.resource_id != effect.resource_id
            or facts.resource_revision != effect.resource_revision
            or facts.tool != effect.tool
            or effect.tool not in effect.tools
            or facts.grant_revision < 1
            or facts.arguments_digest != effect.arguments_digest
        ):
            raise ValueError("The private decision does not bind this terminal effect")

    def require_lease(self, current: tuple[str, str, int] | None) -> None:
        if current is not None and current != self.lease_identity:
            raise ValueError("Worker is leased to another current session")
