"""Bind independently verified owner revisions to one original effect.

These facts describe a verified proof; constructing them does not authenticate
the producer. The transport remains responsible for signature verification.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


class SourceProofMismatch(ValueError):
    """Current authority no longer authorizes the original command."""


@dataclass(frozen=True, slots=True)
class EffectSubject:
    owner: str
    audience: str
    operation: str
    idempotency_key: str
    payload_sha256: str
    recipient_service_uuid: UUID
    recipient_instance_uuid: UUID
    actor_uuid: UUID
    project_uuid: UUID
    session_uuid: UUID
    operation_uuid: UUID


@dataclass(frozen=True, slots=True)
class AuthorityEpochs:
    identity: UUID
    platform: UUID
    access: UUID


@dataclass(frozen=True, slots=True)
class AuthorityVersions:
    identity: int
    control: int
    access: int


@dataclass(frozen=True, slots=True)
class ResourceVersions:
    control: int
    team_uuid: UUID | None
    team: int | None
    team_resource: int | None

    def require_owner(self, scope: str | None, owner_uuid: UUID | None) -> None:
        if scope == "team" and self.team_uuid != owner_uuid:
            raise SourceProofMismatch("team owner changed")
        if scope == "project" and self.team_uuid is not None:
            raise SourceProofMismatch("unexpected team owner")

    def require_complete_scope(self, scope: str | None) -> None:
        if scope == "team" and (self.team is None or self.team_resource is None):
            raise SourceProofMismatch("team revisions missing")
        if scope == "project" and (self.team is not None or self.team_resource is not None):
            raise SourceProofMismatch("unexpected team revisions")


@dataclass(frozen=True, slots=True)
class SourceProofRequirement:
    subject: EffectSubject
    versions: AuthorityVersions
    epochs: AuthorityEpochs
    owner_scope: str | None
    owner_uuid: UUID | None
    recipient_expires_at: datetime
    grant_expires_at: datetime
    # Status inspection must retain the exact original resource revisions.
    # First dispatch obtains them from the independently verified producer.
    resources: ResourceVersions | None = None


@dataclass(frozen=True, slots=True)
class SourceProof:
    subject: EffectSubject
    versions: AuthorityVersions
    epochs: AuthorityEpochs
    resources: ResourceVersions
    expires_at: datetime

    def require_for(self, requirement: SourceProofRequirement) -> None:
        if self.subject != requirement.subject:
            raise SourceProofMismatch("effect subject changed")
        if self.versions != requirement.versions or self.epochs != requirement.epochs:
            raise SourceProofMismatch("authority revision changed")
        self.resources.require_owner(requirement.owner_scope, requirement.owner_uuid)
        if requirement.resources is None:
            self.resources.require_complete_scope(requirement.owner_scope)
        elif self.resources != requirement.resources:
            raise SourceProofMismatch("original resource revision changed")
        if self.expires_at > min(requirement.recipient_expires_at, requirement.grant_expires_at):
            raise SourceProofMismatch("proof exceeds authority lifetime")
