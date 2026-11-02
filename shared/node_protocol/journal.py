"""Purpose-bound Node execution journal protocol; PostgreSQL stays with Resources.

These are transport records, never desired-state or authorization grants. Keys
are supplied by independently pinned enrollment, never by the request itself.
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Annotated, Literal, Self
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import UUID4, BaseModel, Field, model_validator

from .control import ControlCommand
from .diagnostics import FailureDiagnostic
from .forward import TransportProof
from .models import Contract, Deployment, NodeRecord

REQUEST_DOMAIN = b"briareus:node-journal-request:v1\x00"
REPLY_DOMAIN = b"briareus:resources-journal-reply:v1\x00"
MAX_REQUEST_BYTES = 65_536
MAX_REPLY_BYTES = 1_048_576
JournalPhase = Literal[
    "queued", "pulling", "stopping", "creating", "checking", "rolling_back", "succeeded", "failed"
]
JournalError = Literal[
    "UPDATE_FAILED", "ROLLBACK_FAILED", "CONTROLLER_INTERRUPTED", "UNMANAGED_INSTANCE"
]
Signature = Annotated[str, Field(min_length=1, max_length=128)]
Container = Annotated[str, Field(min_length=1, max_length=128)]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class AcquireJournal(Contract):
    action: Literal["acquire"] = "acquire"
    lease_seconds: int = Field(default=30, strict=True, ge=5, le=30)


class RenewJournal(Contract):
    action: Literal["renew"] = "renew"
    lease_seconds: int = Field(default=30, strict=True, ge=5, le=30)


class ReleaseJournal(Contract):
    action: Literal["release"] = "release"


class GetConfiguration(Contract):
    action: Literal["configuration"] = "configuration"


class ConfigureJournal(Contract):
    action: Literal["configure"] = "configure"
    core_command: ControlCommand
    core_signature: Signature

    @model_validator(mode="after")
    def exact_command(self) -> Self:
        if self.core_command.action != "configure":
            raise ValueError("Journal configuration requires a signed configure command")
        return self


class GetOperation(Contract):
    action: Literal["get"] = "get"
    operation_uuid: UUID4


class ReserveOperation(Contract):
    action: Literal["reserve"] = "reserve"
    core_command: ControlCommand
    core_signature: Signature

    @model_validator(mode="after")
    def exact_command(self) -> Self:
        if self.core_command.action != "apply":
            raise ValueError("Journal reservation requires a signed apply command")
        return self


class PhaseOperation(Contract):
    action: Literal["phase"] = "phase"
    operation_uuid: UUID4
    phase: JournalPhase
    container: Container | None = None
    error: JournalError | None = None
    diagnostic: FailureDiagnostic | None = None


class ApplyOperation(Contract):
    action: Literal["applied"] = "applied"
    operation_uuid: UUID4
    desired: Deployment
    container: Container


class RestoreOperation(Contract):
    action: Literal["restore"] = "restore"
    operation_uuid: UUID4
    previous: Deployment
    container: Container


class MatchApplied(Contract):
    action: Literal["matches_applied"] = "matches_applied"
    desired: Deployment
    container: Container


class FindFailedCandidate(Contract):
    action: Literal["failed_candidate"] = "failed_candidate"
    desired: Deployment
    container: Container
    fingerprint: Digest
    before_sequence: int = Field(strict=True, ge=1, lt=2**63)


class ForwardTarget(Contract):
    action: Literal["forward_target"] = "forward_target"
    proof: TransportProof
    gateway_signature: Signature


class AdmitForward(Contract):
    action: Literal["admit_forward"] = "admit_forward"
    proof: TransportProof
    gateway_signature: Signature


class ReadEvents(Contract):
    action: Literal["events_after"] = "events_after"
    cursor: int = Field(strict=True, ge=0, lt=2**63)


class ReadCursor(Contract):
    action: Literal["event_cursor"] = "event_cursor"


JournalAction = Annotated[
    AcquireJournal
    | RenewJournal
    | ReleaseJournal
    | GetConfiguration
    | ConfigureJournal
    | GetOperation
    | ReserveOperation
    | PhaseOperation
    | ApplyOperation
    | RestoreOperation
    | MatchApplied
    | FindFailedCandidate
    | ForwardTarget
    | AdmitForward
    | ReadEvents
    | ReadCursor,
    Field(discriminator="action"),
]


class JournalRequest(Contract):
    purpose: Literal["execution-journal"] = "execution-journal"
    audience: Literal["resources"] = "resources"
    node_uuid: UUID4
    request_uuid: UUID4
    session_uuid: UUID4
    lease_epoch: int | None = Field(default=None, strict=True, ge=1, lt=2**63)
    issued_at: int = Field(strict=True, ge=1)
    expires_at: int = Field(strict=True, ge=1)
    payload: JournalAction

    @property
    def action(self) -> str:
        return self.payload.action

    @model_validator(mode="after")
    def bounded_delegation(self) -> Self:
        if not 0 < self.expires_at - self.issued_at <= 15:
            raise ValueError("Bounded journal request lifetime required")
        if (self.action == "acquire") != (self.lease_epoch is None):
            raise ValueError("Only acquisition omits the writer epoch")
        _require_payload_node(self.payload, self.node_uuid)
        return self

    def signing_bytes(self) -> bytes:
        return REQUEST_DOMAIN + _canonical(self)


def _require_payload_node(payload: JournalAction, node_uuid: UUID) -> None:
    candidate: UUID | None = None
    if isinstance(payload, (ConfigureJournal, ReserveOperation)):
        candidate = payload.core_command.node_uuid
    elif isinstance(payload, (ApplyOperation, MatchApplied, FindFailedCandidate)):
        candidate = payload.desired.node_uuid
    elif isinstance(payload, RestoreOperation):
        candidate = payload.previous.node_uuid
    elif isinstance(payload, (ForwardTarget, AdmitForward)):
        candidate = payload.proof.node_uuid
    if candidate is not None and candidate != node_uuid:
        raise ValueError("Journal payload belongs to another node")


class JournalOperation(Contract):
    id: str = Field(min_length=36, max_length=36)
    placement: str = Field(min_length=36, max_length=36)
    sequence: int = Field(strict=True, ge=1, lt=2**63)
    desired: Deployment
    fingerprint: Digest
    phase: JournalPhase
    previous: Deployment | None = None
    container: Container | None = None
    error: JournalError | None = None
    diagnostic: FailureDiagnostic | None = None


class JournalConfiguration(Contract):
    sequence: int = Field(strict=True, ge=1, lt=2**63)
    record: NodeRecord


class JournalOperationEvent(Contract):
    operation_uuid: UUID4
    sequence: int = Field(strict=True, ge=1, lt=2**63)
    phase: JournalPhase
    error: JournalError | None = None
    diagnostic: FailureDiagnostic | None = None


class JournalConfigurationEvent(Contract):
    node_uuid: UUID4
    enabled: bool = Field(strict=True)
    sequence: int = Field(strict=True, ge=1, lt=2**63)


class JournalEvent(Contract):
    cursor: int = Field(strict=True, ge=1, lt=2**63)
    topic: Literal["configuration", "operation"]
    payload: JournalOperationEvent | JournalConfigurationEvent
    created_at: str = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def exact_event(self) -> Self:
        if (self.topic == "operation") != isinstance(self.payload, JournalOperationEvent):
            raise ValueError("Journal event topic and payload differ")
        return self


class JournalResult(Contract):
    lease_epoch: int | None = Field(default=None, strict=True, ge=1, lt=2**63)
    lease_expires_at: int | None = Field(default=None, strict=True, ge=1)
    operation: JournalOperation | None = None
    configuration: JournalConfiguration | None = None
    events: tuple[JournalEvent, ...] = Field(default=(), max_length=128)
    cursor: int | None = Field(default=None, strict=True, ge=0, lt=2**63)
    container: Container | None = None
    matched: bool | None = Field(default=None, strict=True)
    error: Literal["JOURNAL_CONFLICT", "JOURNAL_UNAVAILABLE", "JOURNAL_REJECTED"] | None = None


class JournalReply(Contract):
    purpose: Literal["execution-journal"] = "execution-journal"
    audience: Literal["node"] = "node"
    node_uuid: UUID4
    request_uuid: UUID4
    request_digest: Digest
    result_digest: Digest
    status_code: int = Field(strict=True, ge=100, le=599)
    issued_at: int = Field(strict=True, ge=1)
    expires_at: int = Field(strict=True, ge=1)
    result: JournalResult

    @model_validator(mode="after")
    def bounded_reply(self) -> Self:
        if not 0 < self.expires_at - self.issued_at <= 15:
            raise ValueError("Bounded journal reply lifetime required")
        if self.result_digest != hashlib.sha256(_canonical(self.result)).hexdigest():
            raise ValueError("Journal result digest mismatch")
        return self

    def signing_bytes(self) -> bytes:
        return REPLY_DOMAIN + _canonical(self)


class SignedJournalRequest(Contract):
    request: JournalRequest
    signature: Signature


class SignedJournalReply(Contract):
    reply: JournalReply
    signature: Signature


def _canonical(value: BaseModel) -> bytes:
    return json.dumps(
        value.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode()


def sign_request(request: JournalRequest, key: Ed25519PrivateKey) -> SignedJournalRequest:
    return SignedJournalRequest(
        request=request, signature=base64.b64encode(key.sign(request.signing_bytes())).decode()
    )


def verify_request(
    envelope: SignedJournalRequest,
    key: Ed25519PublicKey,
    *,
    node_uuid: UUID,
    now: int,
) -> JournalRequest:
    request = envelope.request
    _require_fresh(request.issued_at, request.expires_at, now)
    if request.node_uuid != node_uuid:
        raise ValueError("Journal request scope mismatch")
    _verify_signature(key, envelope.signature, request.signing_bytes())
    return request


def sign_reply(
    request: JournalRequest,
    result: JournalResult,
    key: Ed25519PrivateKey,
    *,
    status_code: int,
    now: int,
) -> SignedJournalReply:
    reply = JournalReply(
        node_uuid=request.node_uuid,
        request_uuid=request.request_uuid,
        request_digest=hashlib.sha256(request.signing_bytes()).hexdigest(),
        result_digest=hashlib.sha256(_canonical(result)).hexdigest(),
        status_code=status_code,
        issued_at=now,
        expires_at=now + 15,
        result=result,
    )
    return SignedJournalReply(
        reply=reply, signature=base64.b64encode(key.sign(reply.signing_bytes())).decode()
    )


def verify_reply(
    envelope: SignedJournalReply,
    request: JournalRequest,
    key: Ed25519PublicKey,
    *,
    now: int,
) -> JournalReply:
    reply = envelope.reply
    _require_fresh(reply.issued_at, reply.expires_at, now)
    if (
        reply.node_uuid != request.node_uuid
        or reply.request_uuid != request.request_uuid
        or reply.request_digest != hashlib.sha256(request.signing_bytes()).hexdigest()
    ):
        raise ValueError("Journal reply scope mismatch")
    _verify_signature(key, envelope.signature, reply.signing_bytes())
    return reply


def _require_fresh(issued_at: int, expires_at: int, now: int) -> None:
    if issued_at > now + 5 or expires_at <= now:
        raise ValueError("Stale journal proof")


def _verify_signature(key: Ed25519PublicKey, signature: str, body: bytes) -> None:
    try:
        key.verify(base64.b64decode(signature, validate=True), body)
    except (ValueError, InvalidSignature):
        raise ValueError("Journal signature rejected") from None
