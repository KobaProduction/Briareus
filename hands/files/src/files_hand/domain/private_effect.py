"""Exact signed private Files effect binding and lifetime."""

from dataclasses import dataclass
from uuid import UUID

from runtime_peer.domain.private_effect import PrivateEffectFacts


@dataclass(frozen=True, slots=True)
class PrivateEffectBinding:
    project_uuid: UUID
    resource_id: str
    resource_revision: int
    tool: str
    arguments_digest: str


@dataclass(frozen=True, slots=True)
class PrivateFilesDecision:
    facts: PrivateEffectFacts

    def require_binding(self, binding: PrivateEffectBinding) -> None:
        facts = self.facts
        if not 0 < facts.expires_at - facts.issued_at <= 5:
            raise ValueError("Effect binding mismatch")
        if facts.not_before != facts.issued_at or facts.grant_revision < 1:
            raise ValueError("Effect binding mismatch")
        actual = (
            facts.project_uuid,
            facts.resource_id,
            facts.resource_revision,
            facts.tool,
            facts.arguments_digest,
        )
        expected = (
            binding.project_uuid,
            binding.resource_id,
            binding.resource_revision,
            binding.tool,
            binding.arguments_digest,
        )
        if actual != expected:
            raise ValueError("Effect binding mismatch")

    def require_output_authority(self, now: float) -> None:
        if now >= self.facts.expires_at:
            raise ValueError("Core authority expired before output")
