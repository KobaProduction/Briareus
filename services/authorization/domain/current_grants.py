"""Trusted owner grant facts required before an external policy engine runs."""

import re
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CedarOperation:
    actor_uuid: UUID
    agent_session_uuid: UUID
    project_uuid: UUID
    action: str
    resource_type: str
    resource_uuid: UUID | str


@dataclass(frozen=True, slots=True)
class CurrentGrant:
    actor_uuid: UUID
    agent_session_uuid: UUID
    project_uuid: UUID
    action: str
    resource_uuid: UUID | str | None
    active: bool
    expires_at: datetime
    version: int
    minimum_current_version: int
    is_elevated: bool = False

    def matches(self, operation: CedarOperation, now: datetime) -> bool:
        current = (
            now.tzinfo is not None
            and self.expires_at.tzinfo is not None
            and self.active
            and self.expires_at > now
            and self.version >= 1
            and self.minimum_current_version >= 1
            and self.version >= self.minimum_current_version
        )
        identity_matches = (
            self.actor_uuid == operation.actor_uuid
            and self.agent_session_uuid == operation.agent_session_uuid
            and self.project_uuid == operation.project_uuid
            and self.action == operation.action
        )
        resource_matches = (
            self.resource_uuid is None or self.resource_uuid == operation.resource_uuid
        )
        operation_valid = (
            bool(operation.action)
            and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", operation.resource_type) is not None
        )
        return current and identity_matches and resource_matches and operation_valid


@dataclass(frozen=True, slots=True)
class ProjectGrantState:
    session_uuid: UUID | None
    actor_uuid: UUID
    project_uuid: UUID
    status: str
    revoked_at: datetime | None
    version: int
    operations: tuple[str, ...] | None

    def permits(
        self,
        *,
        actor_uuid: UUID,
        project_uuid: UUID,
        operation: str,
        expected_version: int,
    ) -> bool:
        identity_matches = (
            self.session_uuid is not None
            and self.actor_uuid == actor_uuid
            and self.project_uuid == project_uuid
        )
        current = (
            self.status == "active"
            and self.revoked_at is None
            and self.version == expected_version
            and self.version >= 1
        )
        if not (identity_matches and current) or self.operations is None:
            return False
        return operation == "mcp.connect" or operation in self.operations
