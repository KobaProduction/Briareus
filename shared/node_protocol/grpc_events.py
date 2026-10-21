"""Verify node event stream identity, subscription lease and contiguous durable cursor."""
import hashlib
import time

from cryptography.exceptions import InvalidSignature

from . import node_pb2 as pb
from .grpc_codec import known, decode_operation
from .replies import NodeReplyVerifier

EVENT_DOMAIN=b"briareus:node-event\0"


class NodeEventVerifier:
    def __init__(self, public_key, command):
        if command.action!="watch":
            raise ValueError("Signed event subscription required")
        self.key=NodeReplyVerifier(public_key).key
        self.command,self.cursor=command,command.after_event

    def verify(self, envelope):
        try:
            known(envelope)
            unsigned=pb.SignedEvent()
            unsigned.CopyFrom(envelope)
            unsigned.ClearField("signature")
            self.key.verify(envelope.signature,EVENT_DOMAIN+unsigned.SerializeToString(deterministic=True))
            event=envelope.event
            now=int(time.time())
            if (event.node_uuid!=str(self.command.node_uuid) or envelope.subscription_uuid!=str(self.command.operation_uuid)
                or envelope.request_digest!=hashlib.sha256(self.command.signing_bytes()).digest()
                or event.cursor!=self.cursor+1 or envelope.issued_at>now+5 or envelope.expires_at<=now
                or not 0<envelope.expires_at-envelope.issued_at<=15
                or envelope.expires_at>self.command.expires_at or self.command.expires_at<=now):
                raise ValueError("Wrong or stale node event")
            kind=event.WhichOneof("payload")
            if kind=="operation" and event.topic==pb.MODULE_OPERATION:
                payload=decode_operation(event.operation)
            elif kind=="configuration" and event.topic==pb.NODE_CONFIGURATION:
                payload={"node_uuid":event.configuration.node_uuid,"sequence":event.configuration.sequence,
                    "enabled":event.configuration.enabled}
                if payload["node_uuid"]!=event.node_uuid:
                    raise ValueError("Wrong node configuration event")
            else:
                raise ValueError("Unknown node event payload")
            self.cursor=event.cursor
            return {"cursor":self.cursor,"node_uuid":event.node_uuid,"topic":kind,
                "created_at":event.created_at.ToJsonString(),"payload":payload}
        except (ValueError,TypeError,InvalidSignature):
            raise ValueError("Node event not authenticated; recover authoritative state") from None
