"""Common signed effect facts; each resource owner retains its own admission policy."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PrivateEffectFacts:
    token_uuid: UUID
    actor_uuid: UUID
    session_uuid: UUID
    operation_uuid: UUID
    issued_at: int
    not_before: int | float
    expires_at: int
    project_uuid: UUID
    resource_id: str
    resource_revision: int | float
    tool: str
    arguments_digest: str
    grant_revision: int
