"""Serialize the unchanged public event protobuf and its request-bound signature."""

import hashlib
from datetime import datetime
from uuid import UUID

from node_agent.identity import NodeIdentity
from node_protocol import node_pb2 as pb
from node_protocol.control import ControlCommand
from node_protocol.grpc_codec import encode_operation
from node_protocol.grpc_events import EVENT_DOMAIN
from node_protocol.journal import JournalConfigurationEvent, JournalEvent, JournalOperationEvent
from node_protocol.reply_wire import OperationWire


def signed_event(
    row: JournalEvent,
    command: ControlCommand,
    identity: NodeIdentity,
    node_uuid: UUID,
    now: int,
) -> pb.SignedEvent:
    event = pb.Event(node_uuid=str(node_uuid), cursor=row.cursor)
    event.created_at.FromDatetime(datetime.fromisoformat(row.created_at))
    payload = row.payload
    if isinstance(payload, JournalOperationEvent):
        event.topic = pb.MODULE_OPERATION
        event.operation.CopyFrom(
            encode_operation(OperationWire.model_validate(payload, from_attributes=True))
        )
    elif isinstance(payload, JournalConfigurationEvent):
        event.topic = pb.NODE_CONFIGURATION
        event.configuration.CopyFrom(
            pb.Configuration(
                node_uuid=str(payload.node_uuid), enabled=payload.enabled, sequence=payload.sequence
            )
        )
    else:
        raise ValueError("Known journal event payload required")
    envelope = pb.SignedEvent(
        event=event,
        subscription_uuid=str(command.operation_uuid),
        issued_at=now,
        expires_at=min(now + 15, command.expires_at),
        request_digest=hashlib.sha256(command.signing_bytes()).digest(),
    )
    envelope.signature = identity.key.sign(
        EVENT_DOMAIN + envelope.SerializeToString(deterministic=True)
    )
    return envelope
