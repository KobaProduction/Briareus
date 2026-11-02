"""Original-operation identity and current per-owner BFF evidence invariants."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from common.domain.owner_authority import OwnerAuthorityUnavailable

BffOwner = Literal["identity", "access", "control", "catalog"]
Phase = Literal["pending", "unknown", "reconciling", "confirmed", "denied"]


def canonical_original_identity(operation_uuid: UUID, key: str | None) -> str:
    """The canonical UUIDv4 key is the operation itself; never invent a mapping."""
    if operation_uuid.version != 4 or not isinstance(key, str):
        raise OwnerAuthorityUnavailable("original signed Operation-UUID must be v4")
    if key != str(operation_uuid):
        raise OwnerAuthorityUnavailable(
            "Operation-UUID and Idempotency-Key are different original operations"
        )
    return hashlib.sha256(key.encode("ascii")).hexdigest()


@dataclass(frozen=True, slots=True)
class OriginalBffSelector:
    owner: BffOwner
    actor_user_id: UUID
    operation_uuid: UUID
    original_key: str
    original_operation: str
    scope_sha256: str
    binding_sha256: str
    recipient_service_id: UUID
    recipient_instance_uuid: UUID

    def validate(self) -> str:
        key_digest = canonical_original_identity(self.operation_uuid, self.original_key)
        if (
            self.actor_user_id.version != 4
            or self.recipient_service_id.version != 4
            or self.recipient_instance_uuid.version != 4
            or not self.original_operation
            or len(self.original_operation) > 128
        ):
            raise OwnerAuthorityUnavailable("invalid signed original BFF selector")
        return key_digest


@dataclass(frozen=True, slots=True)
class CurrentOriginalBffSourceGrant:
    actor_user_id: UUID
    operation_uuid: UUID
    original_key: str
    original_operation: str
    original_project_scope: str
    scope_sha256: str
    binding_sha256: str
    owner_revision: str
    recipient_service_id: UUID
    recipient_instance_uuid: UUID
    expires_at: datetime

    def require_binding(self, selector: OriginalBffSelector, now: datetime) -> None:
        if (
            self.actor_user_id != selector.actor_user_id
            or self.operation_uuid != selector.operation_uuid
            or self.original_key != selector.original_key
            or self.original_operation != selector.original_operation
            or self.scope_sha256 != selector.scope_sha256
            or self.binding_sha256 != selector.binding_sha256
            or self.recipient_service_id != selector.recipient_service_id
            or self.recipient_instance_uuid != selector.recipient_instance_uuid
            or not self.original_project_scope
            or not 1 <= len(self.owner_revision) <= 160
            or self.expires_at.tzinfo is None
            or not now < self.expires_at <= now + timedelta(seconds=15)
        ):
            raise OwnerAuthorityUnavailable("original signed owner grant changed")

    def require_continuity(self, original: CurrentOriginalBffSourceGrant) -> None:
        if (
            self.original_project_scope != original.original_project_scope
            or self.owner_revision != original.owner_revision
            or self.scope_sha256 != original.scope_sha256
            or self.binding_sha256 != original.binding_sha256
        ):
            raise OwnerAuthorityUnavailable("original grant revoked before BFF status signature")


@dataclass(frozen=True, slots=True)
class StoredOriginalOwnerState:
    status: str
    encrypted_outcome_present: bool

    def phase(self) -> Phase:
        if self.status in {"pending", "unknown"}:
            return "unknown"
        if self.status == "denied":
            return "denied"
        if self.status in {"completed", "reconciled"} and self.encrypted_outcome_present:
            return "confirmed"
        raise OwnerAuthorityUnavailable("original owner effect state is not verified")


@dataclass(frozen=True, slots=True)
class OriginalOwnerStatusFact:
    selector: OriginalBffSelector
    original_idempotency_key_sha256: str
    owner_revision: str
    phase: Phase
    issued_at: datetime
    expires_at: datetime
