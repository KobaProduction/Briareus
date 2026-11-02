"""Only current owner-bound AgentSession operations can become Access proof."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

_COMMAND_GRANTS = {
    "files.write.reserve": "files.write",
    "files.write.dispatch": "files.write",
    "files.write.reconcile": "files.write",
    "credential.reserve": "integrations.use",
    "credential.redeem": "integrations.use",
    "catalog.integration.create": "integrations.manage",
    "catalog.integration.rotate": "integrations.manage",
    "catalog.integration.revoke": "integrations.manage",
    "catalog.variable.create": "variables.manage",
    "catalog.variable.rotate": "variables.manage",
    "catalog.variable.revoke": "variables.manage",
    "catalog.variable.reserve": "variables.use",
    "catalog.variable.redeem": "variables.use",
    "reverse.import.reserve": "analysis.import",
    "reverse.import.dispatch": "analysis.import",
    "reverse.import.reconcile": "analysis.import",
    "agent.create": "agents.manage",
}


class AccessProofUnavailable(Exception):
    """Current Access authority cannot prove the requested exact operation."""


@dataclass(frozen=True, slots=True)
class AccessProofQuery:
    operation: str
    caller_uuid: UUID
    project_uuid: UUID
    session_uuid: UUID
    identity_revision: int
    access_revision: int

    def needed_grant(self) -> str:
        needed = _COMMAND_GRANTS.get(self.operation)
        if needed is None:
            raise AccessProofUnavailable("this operation lacks an accepted Access grant mapping")
        return needed


@dataclass(frozen=True, slots=True)
class VerifiedAccessActor:
    user_id: UUID
    identity_credential_version: int
    recipient_service_id: UUID
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class AccessProofAuthority:
    actor: VerifiedAccessActor
    peer_service_uuid: UUID
    peer_audience: str
    peer_expires_at: datetime

    def require_current(self, query: AccessProofQuery, now: datetime) -> None:
        if self.peer_audience != "briareus:access" or self.peer_expires_at <= now:
            raise AccessProofUnavailable("Access caller is not bound to verified Identity")
        actor_matches = (
            self.actor.user_id == query.caller_uuid
            and self.actor.identity_credential_version == query.identity_revision
            and self.actor.recipient_service_id == self.peer_service_uuid
        )
        if (
            not actor_matches
            or self.actor.expires_at.tzinfo is None
            or self.actor.expires_at <= now
        ):
            raise AccessProofUnavailable("Access caller is not bound to verified Identity")


@dataclass(frozen=True, slots=True)
class AccessProofSession:
    session_uuid: UUID
    project_uuid: UUID
    creator_uuid: UUID
    version: int
    status: str
    hard_expires_at: datetime
    grants: tuple[str, ...] | None

    def require_current(self, query: AccessProofQuery, needed_grant: str, now: datetime) -> None:
        identity_matches = (
            self.session_uuid == query.session_uuid
            and self.project_uuid == query.project_uuid
            and self.creator_uuid == query.caller_uuid
        )
        current = (
            self.status == "active"
            and self.hard_expires_at > now
            and self.version == query.access_revision
        )
        if not identity_matches or not current:
            raise AccessProofUnavailable("Access session revoked, expired or wrong Project")
        if self.grants is None or needed_grant not in self.grants:
            raise AccessProofUnavailable("required live AgentSession grant not active")
