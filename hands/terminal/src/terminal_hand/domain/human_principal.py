"""A project user owns Terminal jobs independently of agent grants."""

import hashlib
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class HumanOperationPrincipal:
    actor_uuid: UUID
    project_uuid: UUID
    operation_uuid: UUID

    @property
    def namespace(self) -> str:
        identity = f"human:{self.actor_uuid}:{self.project_uuid}"
        return "human-" + hashlib.sha256(identity.encode()).hexdigest()
