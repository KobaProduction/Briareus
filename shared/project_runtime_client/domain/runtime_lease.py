"""A ledger snapshot binds one scope; takeover also requires confirmed cleanup."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from project_runtime_client.domain._code_error import _CodeError

from .identifiers import valid_uuid
from .revisions import valid_project_revision

LeaseKind = Literal["files", "terminal", "web_managed", "web_remote", "reverse"]
LeaseAudience = Literal["files", "terminal", "web", "reverse"]
LeaseState = Literal["active", "lost", "expired", "revoked", "closed"]
CleanupState = Literal["not_needed", "pending", "confirmed", "unknown"]
_KIND_AUDIENCE: dict[LeaseKind, LeaseAudience] = {
    "files": "files",
    "terminal": "terminal",
    "web_managed": "web",
    "web_remote": "web",
    "reverse": "reverse",
}


class A9SignedLeaseUntrusted(_CodeError):
    pass


@dataclass(frozen=True, slots=True)
class RuntimeLeaseScope:
    project_uuid: UUID
    session_uuid: UUID
    actor_uuid: UUID
    service_uuid: UUID
    runtime_session_uuid: UUID
    kind: LeaseKind


@dataclass(frozen=True, slots=True)
class RuntimeLeaseExpectation:
    scope: RuntimeLeaseScope
    instance_uuid: UUID
    audience: LeaseAudience
    decision_version: int
    access_revision: str | None
    permit_expires_at: datetime

    def require_trusted(self, now: datetime) -> None:
        identifiers = (
            self.scope.service_uuid,
            self.instance_uuid,
            self.scope.project_uuid,
            self.scope.session_uuid,
            self.scope.actor_uuid,
            self.scope.runtime_session_uuid,
        )
        if (
            not all(valid_uuid(value, version=4) for value in identifiers)
            or _KIND_AUDIENCE.get(self.scope.kind) != self.audience
            or type(self.decision_version) is not int
            or self.decision_version < 1
            or not valid_project_revision(self.access_revision)
            or self.permit_expires_at.tzinfo is None
            or self.permit_expires_at <= now
        ):
            raise A9SignedLeaseUntrusted("A9_LEASE_TRUSTED_EXPECTATIONS_INVALID")


@dataclass(frozen=True, slots=True)
class RuntimeLeaseClaims:
    jti: UUID
    purpose: str
    recipient_service: UUID
    recipient_instance: UUID
    access_revision: str
    session_version: int
    issued_at: int
    not_before: int
    expires_at: int

    def require_for(self, expected: RuntimeLeaseExpectation) -> None:
        if (
            not valid_uuid(self.jti, version=4)
            or self.purpose != "runtime-ledger-attestation-v1"
            or self.recipient_service != expected.scope.service_uuid
            or self.recipient_instance != expected.instance_uuid
            or self.access_revision != expected.access_revision
            or self.session_version != expected.decision_version
            or not 0 < self.expires_at - self.issued_at <= 30
        ):
            raise A9SignedLeaseUntrusted("A9_LEASE_CLAIMS_SCOPE_MISMATCH")


@dataclass(frozen=True, slots=True)
class RuntimeLeaseLifetime:
    idle_expires_at: datetime
    hard_expires_at: datetime
    lease_expires_at: datetime

    def require_valid(self, *, state: LeaseState, token_expires_at: int, now: datetime) -> None:
        if not all(
            value.tzinfo is not None
            for value in (
                self.idle_expires_at,
                self.hard_expires_at,
                self.lease_expires_at,
            )
        ):
            raise A9SignedLeaseUntrusted("A9_LEASE_SIGNED_SQL_SNAPSHOT_MISMATCH")
        if self.lease_expires_at > self.hard_expires_at:
            raise A9SignedLeaseUntrusted("A9_LEASE_SIGNED_SQL_SNAPSHOT_MISMATCH")
        if state == "active" and (
            self.hard_expires_at <= now
            or self.lease_expires_at <= now
            or token_expires_at > int(self.lease_expires_at.timestamp())
        ):
            raise A9SignedLeaseUntrusted("A9_LEASE_SIGNED_SQL_SNAPSHOT_MISMATCH")


@dataclass(frozen=True, slots=True)
class RuntimeLeaseSnapshot:
    scope: RuntimeLeaseScope
    owner_instance_uuid: UUID
    nonce: UUID
    state: LeaseState
    cleanup: CleanupState
    lifetime: RuntimeLeaseLifetime

    def require_for(
        self,
        expected: RuntimeLeaseExpectation,
        *,
        attestation_expires_at: datetime,
        token_expires_at: int,
        now: datetime,
    ) -> None:
        if (
            self.scope != expected.scope
            or not valid_uuid(self.scope.runtime_session_uuid, version=4)
            or not valid_uuid(self.nonce, version=4)
            or not valid_uuid(self.owner_instance_uuid, version=4)
            or _KIND_AUDIENCE.get(self.scope.kind) != expected.audience
        ):
            raise A9SignedLeaseUntrusted("A9_LEASE_SIGNED_SQL_SNAPSHOT_MISMATCH")
        if not isinstance(attestation_expires_at, datetime):
            raise A9SignedLeaseUntrusted("A9_LEASE_SIGNED_SQL_SNAPSHOT_MISMATCH")
        if (
            attestation_expires_at.tzinfo is None
            or int(attestation_expires_at.timestamp()) != token_expires_at
        ):
            raise A9SignedLeaseUntrusted("A9_LEASE_SIGNED_SQL_SNAPSHOT_MISMATCH")
        self.lifetime.require_valid(state=self.state, token_expires_at=token_expires_at, now=now)
        if self.owner_instance_uuid != expected.instance_uuid and (
            self.state not in {"lost", "expired", "revoked", "closed"}
            or self.cleanup != "confirmed"
        ):
            raise A9SignedLeaseUntrusted("A9_LEASE_TAKEOVER_WITHOUT_OS_CLEANUP")
