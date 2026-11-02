"""Single-use credential lease binding and revision fences, without owner storage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


class CredentialLeaseDenied(Exception):
    """A lease is stale, already consumed, or bound to different authority."""


def require_credential_operation(
    operation_uuid: object, resource_uuid: UUID | None, name: str | None
) -> None:
    if not isinstance(operation_uuid, UUID) or operation_uuid.version != 4:
        raise CredentialLeaseDenied("explicit credential resource/operation UUIDv4 required")
    if resource_uuid is None or name is not None:
        raise CredentialLeaseDenied("explicit credential resource/operation UUIDv4 required")


@dataclass(frozen=True, slots=True)
class LeaseServiceBinding:
    service_uuid: UUID | None
    instance_uuid: UUID | None
    audience: str | None
    correlation_uuid: UUID | None

    def matches(self, current: LeaseServiceBinding | None) -> bool:
        if current is None:
            return self.service_uuid is None
        return self == current


@dataclass(frozen=True, slots=True)
class LeaseResourceBinding:
    resource_uuid: UUID
    project_uuid: UUID
    session_uuid: UUID
    actor_uuid: UUID
    kind: str


@dataclass(frozen=True, slots=True)
class LeaseOwnerRevision:
    version: int
    resource_revision: int


@dataclass(frozen=True, slots=True)
class CredentialLeaseState:
    binding: LeaseResourceBinding
    service: LeaseServiceBinding
    session_version: int
    project: LeaseOwnerRevision
    team_version: int | None
    team_resource_revision: int | None
    resource_version: int
    owner_scope: str
    owner_uuid: UUID
    expires_at: datetime
    redeemed_at: datetime | None

    def require_redeem(
        self,
        binding: LeaseResourceBinding,
        service: LeaseServiceBinding | None,
        now: datetime,
    ) -> None:
        if self.redeemed_at is not None or self.expires_at <= now:
            raise CredentialLeaseDenied("credential lease unavailable or expired")
        if self.binding != binding or not self.service.matches(service):
            raise CredentialLeaseDenied("credential lease unavailable or expired")

    def require_session(
        self,
        view_version: int,
        locked_version: int,
        project_uuid: UUID,
        operation_granted: bool,
    ) -> None:
        if view_version != self.session_version or locked_version != self.session_version:
            raise CredentialLeaseDenied("AgentSession grant revision changed")
        if project_uuid != self.binding.project_uuid or not operation_granted:
            raise CredentialLeaseDenied("AgentSession grant revision changed")

    def require_project(self, current: LeaseOwnerRevision) -> None:
        if current != self.project:
            raise CredentialLeaseDenied("Project authorization/resource revision changed")

    def require_team(self, *, team_owned: bool, current: LeaseOwnerRevision | None) -> None:
        if not team_owned:
            if self.team_version is not None:
                raise CredentialLeaseDenied("Project no longer inherits Team resources")
            return
        if current is None or current.version != self.team_version:
            raise CredentialLeaseDenied("Team authorization/resource revision changed")
        if current.resource_revision != self.team_resource_revision:
            raise CredentialLeaseDenied("Team authorization/resource revision changed")

    def require_resource(self, version: int, owner_scope: str, owner_uuid: UUID) -> None:
        if (
            version != self.resource_version
            or owner_scope != self.owner_scope
            or owner_uuid != self.owner_uuid
        ):
            raise CredentialLeaseDenied("resource revoked, moved, or rotated")
