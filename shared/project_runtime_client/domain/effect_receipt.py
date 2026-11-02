"""A signed outcome must describe the exact dispatched command and result."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


class OwnerEffectUnavailable(Exception):
    def __init__(self, code: str, *, unknown: bool = False) -> None:
        self.code = code
        self.outcome_unknown = unknown
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class RevocationFence:
    identity_version: int
    identity_revocation_epoch: int
    identity_authority_epoch: UUID
    control_state_version: int
    control_revision: str
    control_scope_epoch: int
    control_authority_epoch: UUID
    access_session_version: int
    access_revocation_epoch: int
    access_authority_epoch: UUID


@dataclass(frozen=True, slots=True)
class EffectReceiptBinding:
    owner: str
    owner_database: str
    project_uuid: UUID
    actor_uuid: UUID
    session_uuid: UUID
    operation_uuid: UUID
    recipient_service_uuid: UUID
    recipient_instance_uuid: UUID
    phase: str
    action: str
    request_sha256: str
    target_sha256: str
    payload_sha256: str
    fence: RevocationFence


@dataclass(frozen=True, slots=True)
class ReceiptExpectation:
    binding: EffectReceiptBinding
    result_sha256: str
    minimum_revision: int
    recipient_expires_at: datetime
    token_expires_at: datetime
    now: datetime


@dataclass(frozen=True, slots=True)
class ReceiptObservation:
    binding: EffectReceiptBinding
    result_sha256: str
    owner_revision: int
    expires_at: datetime
    state: str

    def require_for(self, expected: ReceiptExpectation) -> None:
        if (
            self.binding != expected.binding
            or self.result_sha256 != expected.result_sha256
            or self.owner_revision < expected.minimum_revision
            or self.expires_at <= expected.now
            or self.expires_at > expected.recipient_expires_at
            or self.expires_at > expected.token_expires_at
        ):
            raise OwnerEffectUnavailable("OWNER_EFFECT_SIGNED_REPLY_INVALID", unknown=True)
        if self.state == "unknown" and expected.binding.phase != "inspect":
            raise OwnerEffectUnavailable("OWNER_EFFECT_REQUIRES_INSPECT", unknown=True)
