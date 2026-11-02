"""Lossless protobuf adapters for independently signed journal records."""

from __future__ import annotations

from collections.abc import Callable
from functools import singledispatch

from google.protobuf.message import Message

from . import journal_pb2 as pb
from . import node_pb2 as node
from .forward import TRANSPORT_PROOF, HumanForwardProof, TransportProof
from .grpc_codec import (
    decode_command,
    decode_deployment,
    decode_record,
    encode_command,
    encode_deployment,
    encode_record,
    known,
)
from .grpc_codec import (
    decode_diagnostic as decode_diagnostic,
)
from .grpc_codec import (
    encode_diagnostic as encode_diagnostic,
)
from .journal import (
    MAX_REPLY_BYTES,
    MAX_REQUEST_BYTES,
    AcquireJournal,
    AdmitForward,
    ApplyOperation,
    ConfigureJournal,
    FindFailedCandidate,
    ForwardTarget,
    GetConfiguration,
    GetOperation,
    JournalAction,
    JournalConfiguration,
    JournalConfigurationEvent,
    JournalEvent,
    JournalOperation,
    JournalOperationEvent,
    JournalReply,
    JournalRequest,
    JournalResult,
    MatchApplied,
    PhaseOperation,
    ReadCursor,
    ReadEvents,
    ReleaseJournal,
    RenewJournal,
    ReserveOperation,
    RestoreOperation,
    SignedJournalReply,
    SignedJournalRequest,
)


def _bounded_known(message: Message, maximum: int) -> None:
    if not 0 < len(message.SerializeToString(deterministic=True)) <= maximum:
        raise ValueError("Bounded journal protobuf message required")
    known(message)


def _encode_forward(value: TransportProof) -> pb.ForwardProof:
    result = pb.ForwardProof(
        node_uuid=str(value.node_uuid),
        placement_uuid=str(value.placement_uuid),
        project_uuid=str(value.project_uuid),
        request_uuid=str(value.request_uuid),
        module=value.module,
        fingerprint=value.fingerprint,
        port=value.port,
        body_digest=value.body_digest,
        bearer_digest=value.bearer_digest,
        effect_digest=value.effect_digest,
        context_digest=value.context_digest,
        protocol_version=value.protocol_version,
        mcp_session_id=value.mcp_session_id,
        issued_at=value.issued_at,
        expires_at=value.expires_at,
    )
    if isinstance(value, HumanForwardProof):
        result.human = True
    else:
        result.agent_session_uuid = str(value.agent_session_uuid)
        result.grant_revision = value.grant_revision
    return result


def _decode_forward(value: pb.ForwardProof) -> TransportProof:
    wire: dict[str, str | int | bool] = {
        "node_uuid": value.node_uuid,
        "placement_uuid": value.placement_uuid,
        "project_uuid": value.project_uuid,
        "request_uuid": value.request_uuid,
        "module": value.module,
        "fingerprint": value.fingerprint,
        "port": value.port,
        "body_digest": value.body_digest,
        "bearer_digest": value.bearer_digest,
        "effect_digest": value.effect_digest,
        "context_digest": value.context_digest,
        "protocol_version": value.protocol_version,
        "mcp_session_id": value.mcp_session_id,
        "issued_at": value.issued_at,
        "expires_at": value.expires_at,
    }
    if value.human:
        if value.agent_session_uuid or value.grant_revision:
            raise ValueError("Mixed human and agent forwarding authority")
        wire["human"] = True
    else:
        wire["agent_session_uuid"] = value.agent_session_uuid
        wire["grant_revision"] = value.grant_revision
    return TRANSPORT_PROOF.validate_python(wire)


@singledispatch
def _encode_action(_value: JournalAction, _target: pb.JournalRequest) -> None:
    raise ValueError("Known journal action required")


@_encode_action.register
def _acquire(value: AcquireJournal, target: pb.JournalRequest) -> None:
    target.acquire.lease_seconds = value.lease_seconds


@_encode_action.register
def _renew(value: RenewJournal, target: pb.JournalRequest) -> None:
    target.renew.lease_seconds = value.lease_seconds


@_encode_action.register
def _release(_value: ReleaseJournal, target: pb.JournalRequest) -> None:
    target.release.SetInParent()


@_encode_action.register
def _configuration(_value: GetConfiguration, target: pb.JournalRequest) -> None:
    target.configuration.SetInParent()


@_encode_action.register
def _configure(value: ConfigureJournal, target: pb.JournalRequest) -> None:
    target.configure.core_command.CopyFrom(encode_command(value.core_command, b"").command)
    target.configure.core_signature = value.core_signature


@_encode_action.register
def _get(value: GetOperation, target: pb.JournalRequest) -> None:
    target.get.operation_uuid = str(value.operation_uuid)


@_encode_action.register
def _reserve(value: ReserveOperation, target: pb.JournalRequest) -> None:
    target.reserve.core_command.CopyFrom(encode_command(value.core_command, b"").command)
    target.reserve.core_signature = value.core_signature


@_encode_action.register
def _phase(value: PhaseOperation, target: pb.JournalRequest) -> None:
    target.phase.operation_uuid = str(value.operation_uuid)
    target.phase.phase = value.phase
    if value.container is not None:
        target.phase.container = value.container
    if value.error is not None:
        target.phase.error = value.error
    if value.diagnostic is not None:
        target.phase.diagnostic.CopyFrom(encode_diagnostic(value.diagnostic))


@_encode_action.register
def _applied(value: ApplyOperation, target: pb.JournalRequest) -> None:
    target.applied.operation_uuid = str(value.operation_uuid)
    target.applied.desired.CopyFrom(encode_deployment(value.desired))
    target.applied.container = value.container


@_encode_action.register
def _restore(value: RestoreOperation, target: pb.JournalRequest) -> None:
    target.restore.operation_uuid = str(value.operation_uuid)
    target.restore.previous.CopyFrom(encode_deployment(value.previous))
    target.restore.container = value.container


@_encode_action.register
def _matches_applied(value: MatchApplied, target: pb.JournalRequest) -> None:
    target.matches_applied.desired.CopyFrom(encode_deployment(value.desired))
    target.matches_applied.container = value.container


@_encode_action.register
def _failed_candidate(value: FindFailedCandidate, target: pb.JournalRequest) -> None:
    target.failed_candidate.desired.CopyFrom(encode_deployment(value.desired))
    target.failed_candidate.container = value.container
    target.failed_candidate.fingerprint = value.fingerprint
    target.failed_candidate.before_sequence = value.before_sequence


@_encode_action.register
def _forward_target(value: ForwardTarget, target: pb.JournalRequest) -> None:
    target.forward_target.proof.CopyFrom(_encode_forward(value.proof))
    target.forward_target.gateway_signature = value.gateway_signature


@_encode_action.register
def _admit_forward(value: AdmitForward, target: pb.JournalRequest) -> None:
    target.admit_forward.proof.CopyFrom(_encode_forward(value.proof))
    target.admit_forward.gateway_signature = value.gateway_signature


@_encode_action.register
def _events_after(value: ReadEvents, target: pb.JournalRequest) -> None:
    target.events_after.cursor = value.cursor


@_encode_action.register
def _event_cursor(_value: ReadCursor, target: pb.JournalRequest) -> None:
    target.event_cursor.SetInParent()


def _decode_phase(value: pb.JournalRequest) -> PhaseOperation:
    phase = value.phase
    return PhaseOperation.model_validate(
        {
            "operation_uuid": phase.operation_uuid,
            "phase": phase.phase,
            "container": phase.container if phase.HasField("container") else None,
            "error": phase.error if phase.HasField("error") else None,
            "diagnostic": decode_diagnostic(phase.diagnostic)
            if phase.HasField("diagnostic")
            else None,
        }
    )


_ACTION_DECODERS: dict[str, Callable[[pb.JournalRequest], JournalAction]] = {
    "acquire": lambda value: AcquireJournal(lease_seconds=value.acquire.lease_seconds),
    "renew": lambda value: RenewJournal(lease_seconds=value.renew.lease_seconds),
    "release": lambda _value: ReleaseJournal(),
    "configuration": lambda _value: GetConfiguration(),
    "configure": lambda value: ConfigureJournal(
        core_command=decode_command(node.SignedCommand(command=value.configure.core_command)),
        core_signature=value.configure.core_signature,
    ),
    "get": lambda value: GetOperation.model_validate({"operation_uuid": value.get.operation_uuid}),
    "reserve": lambda value: ReserveOperation(
        core_command=decode_command(node.SignedCommand(command=value.reserve.core_command)),
        core_signature=value.reserve.core_signature,
    ),
    "phase": _decode_phase,
    "applied": lambda value: ApplyOperation.model_validate(
        {
            "operation_uuid": value.applied.operation_uuid,
            "desired": decode_deployment(value.applied.desired),
            "container": value.applied.container,
        }
    ),
    "restore": lambda value: RestoreOperation.model_validate(
        {
            "operation_uuid": value.restore.operation_uuid,
            "previous": decode_deployment(value.restore.previous),
            "container": value.restore.container,
        }
    ),
    "matches_applied": lambda value: MatchApplied(
        desired=decode_deployment(value.matches_applied.desired),
        container=value.matches_applied.container,
    ),
    "failed_candidate": lambda value: FindFailedCandidate(
        desired=decode_deployment(value.failed_candidate.desired),
        container=value.failed_candidate.container,
        fingerprint=value.failed_candidate.fingerprint,
        before_sequence=value.failed_candidate.before_sequence,
    ),
    "forward_target": lambda value: ForwardTarget(
        proof=_decode_forward(value.forward_target.proof),
        gateway_signature=value.forward_target.gateway_signature,
    ),
    "admit_forward": lambda value: AdmitForward(
        proof=_decode_forward(value.admit_forward.proof),
        gateway_signature=value.admit_forward.gateway_signature,
    ),
    "events_after": lambda value: ReadEvents(cursor=value.events_after.cursor),
    "event_cursor": lambda _value: ReadCursor(),
}


def encode_request(envelope: SignedJournalRequest) -> pb.SignedJournalRequest:
    request = envelope.request
    value = pb.JournalRequest(
        purpose=request.purpose,
        audience=request.audience,
        node_uuid=str(request.node_uuid),
        request_uuid=str(request.request_uuid),
        session_uuid=str(request.session_uuid),
        issued_at=request.issued_at,
        expires_at=request.expires_at,
    )
    if request.lease_epoch is not None:
        value.lease_epoch = request.lease_epoch
    _encode_action(request.payload, value)
    result = pb.SignedJournalRequest(request=value, signature=envelope.signature)
    _bounded_known(result, MAX_REQUEST_BYTES)
    return result


def decode_request(envelope: pb.SignedJournalRequest) -> SignedJournalRequest:
    _bounded_known(envelope, MAX_REQUEST_BYTES)
    if not envelope.HasField("request"):
        raise ValueError("Journal request required")
    value = envelope.request
    action = value.WhichOneof("action")
    if action is None or action not in _ACTION_DECODERS:
        raise ValueError("Known journal action required")
    return SignedJournalRequest(
        request=JournalRequest.model_validate(
            {
                "purpose": value.purpose,
                "audience": value.audience,
                "node_uuid": value.node_uuid,
                "request_uuid": value.request_uuid,
                "session_uuid": value.session_uuid,
                "lease_epoch": value.lease_epoch if value.HasField("lease_epoch") else None,
                "issued_at": value.issued_at,
                "expires_at": value.expires_at,
                "payload": _ACTION_DECODERS[action](value),
            }
        ),
        signature=envelope.signature,
    )


def _encode_operation(value: JournalOperation) -> pb.JournalOperation:
    result = pb.JournalOperation(
        id=value.id,
        placement=value.placement,
        sequence=value.sequence,
        desired=encode_deployment(value.desired),
        fingerprint=value.fingerprint,
        phase=value.phase,
    )
    if value.previous is not None:
        result.previous.CopyFrom(encode_deployment(value.previous))
    if value.container is not None:
        result.container = value.container
    if value.error is not None:
        result.error = value.error
    if value.diagnostic is not None:
        result.diagnostic.CopyFrom(encode_diagnostic(value.diagnostic))
    return result


def _decode_operation(value: pb.JournalOperation) -> JournalOperation:
    return JournalOperation.model_validate(
        {
            "id": value.id,
            "placement": value.placement,
            "sequence": value.sequence,
            "desired": decode_deployment(value.desired),
            "fingerprint": value.fingerprint,
            "phase": value.phase,
            "previous": decode_deployment(value.previous) if value.HasField("previous") else None,
            "container": value.container if value.HasField("container") else None,
            "error": value.error if value.HasField("error") else None,
            "diagnostic": decode_diagnostic(value.diagnostic)
            if value.HasField("diagnostic")
            else None,
        }
    )


def _encode_event(value: JournalEvent) -> pb.JournalEvent:
    result = pb.JournalEvent(cursor=value.cursor, created_at=value.created_at)
    payload = value.payload
    if isinstance(payload, JournalOperationEvent):
        result.operation.CopyFrom(
            node.Operation(
                operation_uuid=str(payload.operation_uuid),
                sequence=payload.sequence,
                phase=payload.phase,
            )
        )
        if payload.error is not None:
            result.operation.error = payload.error
        if payload.diagnostic is not None:
            result.operation.diagnostic.CopyFrom(encode_diagnostic(payload.diagnostic))
    else:
        result.configuration.CopyFrom(
            node.Configuration(
                node_uuid=str(payload.node_uuid),
                enabled=payload.enabled,
                sequence=payload.sequence,
            )
        )
    return result


def _decode_event(value: pb.JournalEvent) -> JournalEvent:
    kind = value.WhichOneof("payload")
    if kind == "operation":
        operation = value.operation
        payload: JournalOperationEvent | JournalConfigurationEvent = (
            JournalOperationEvent.model_validate(
                {
                    "operation_uuid": operation.operation_uuid,
                    "sequence": operation.sequence,
                    "phase": operation.phase,
                    "error": operation.error if operation.HasField("error") else None,
                    "diagnostic": (
                        decode_diagnostic(operation.diagnostic)
                        if operation.HasField("diagnostic")
                        else None
                    ),
                }
            )
        )
        return JournalEvent(
            cursor=value.cursor, topic="operation", payload=payload, created_at=value.created_at
        )
    if kind == "configuration":
        configuration = value.configuration
        payload = JournalConfigurationEvent.model_validate(
            {
                "node_uuid": configuration.node_uuid,
                "enabled": configuration.enabled,
                "sequence": configuration.sequence,
            }
        )
        return JournalEvent(
            cursor=value.cursor, topic="configuration", payload=payload, created_at=value.created_at
        )
    raise ValueError("Typed journal event payload required")


def _encode_result(value: JournalResult) -> pb.JournalResult:
    result = pb.JournalResult(events=[_encode_event(event) for event in value.events])
    _encode_result_scalars(value, result)
    if value.operation is not None:
        result.operation.CopyFrom(_encode_operation(value.operation))
    if value.configuration is not None:
        result.configuration.CopyFrom(
            pb.JournalConfiguration(
                sequence=value.configuration.sequence,
                record=encode_record(value.configuration.record),
            )
        )
    return result


def _encode_result_scalars(value: JournalResult, target: pb.JournalResult) -> None:
    if value.lease_epoch is not None:
        target.lease_epoch = value.lease_epoch
    if value.lease_expires_at is not None:
        target.lease_expires_at = value.lease_expires_at
    if value.cursor is not None:
        target.cursor = value.cursor
    if value.container is not None:
        target.container = value.container
    if value.matched is not None:
        target.matched = value.matched
    if value.error is not None:
        target.error = value.error


def _decode_result(value: pb.JournalResult) -> JournalResult:
    configuration = None
    if value.HasField("configuration"):
        configuration = JournalConfiguration(
            sequence=value.configuration.sequence, record=decode_record(value.configuration.record)
        )
    return JournalResult.model_validate(
        {
            "lease_epoch": value.lease_epoch if value.HasField("lease_epoch") else None,
            "lease_expires_at": value.lease_expires_at
            if value.HasField("lease_expires_at")
            else None,
            "operation": _decode_operation(value.operation)
            if value.HasField("operation")
            else None,
            "configuration": configuration,
            "events": tuple(_decode_event(event) for event in value.events),
            "cursor": value.cursor if value.HasField("cursor") else None,
            "container": value.container if value.HasField("container") else None,
            "matched": value.matched if value.HasField("matched") else None,
            "error": value.error if value.HasField("error") else None,
        }
    )


def encode_reply(envelope: SignedJournalReply) -> pb.SignedJournalReply:
    reply = envelope.reply
    result = pb.SignedJournalReply(
        reply=pb.JournalReply(
            purpose=reply.purpose,
            audience=reply.audience,
            node_uuid=str(reply.node_uuid),
            request_uuid=str(reply.request_uuid),
            request_digest=reply.request_digest,
            result_digest=reply.result_digest,
            status_code=reply.status_code,
            issued_at=reply.issued_at,
            expires_at=reply.expires_at,
            result=_encode_result(reply.result),
        ),
        signature=envelope.signature,
    )
    _bounded_known(result, MAX_REPLY_BYTES)
    return result


def decode_reply(envelope: pb.SignedJournalReply) -> SignedJournalReply:
    _bounded_known(envelope, MAX_REPLY_BYTES)
    if not envelope.HasField("reply") or not envelope.reply.HasField("result"):
        raise ValueError("Journal reply and result required")
    value = envelope.reply
    return SignedJournalReply(
        reply=JournalReply.model_validate(
            {
                "purpose": value.purpose,
                "audience": value.audience,
                "node_uuid": value.node_uuid,
                "request_uuid": value.request_uuid,
                "request_digest": value.request_digest,
                "result_digest": value.result_digest,
                "status_code": value.status_code,
                "issued_at": value.issued_at,
                "expires_at": value.expires_at,
                "result": _decode_result(value.result),
            }
        ),
        signature=envelope.signature,
    )
