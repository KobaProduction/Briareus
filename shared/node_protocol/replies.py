"""Verify a node reply against an independently pinned public service key."""

import base64
import hashlib
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .browser_observation import BrowserObservationWire
from .control import ControlCommand, canonical
from .domain.observations import NodeReply
from .reply_wire import NodeReplyWire, ReplyPayload


class ReplyRejected(ValueError):
    pass


def require_observation_reply(command: ControlCommand, payload: ReplyPayload) -> None:
    if isinstance(payload, BrowserObservationWire) and (
        command.action != "observe_browser" or payload.target != command.browser_observation
    ):
        raise ValueError("Browser observation belongs to another request target")


class NodeReplyVerifier:
    def __init__(self, public_key: bytes) -> None:
        key = serialization.load_pem_public_key(public_key)
        if not isinstance(key, Ed25519PublicKey):
            raise ReplyRejected("Pinned node Ed25519 public key required")
        self.key = key

    def verify(self, command: ControlCommand, status: int, envelope: NodeReplyWire) -> NodeReply:
        try:
            if not isinstance(envelope, NodeReplyWire):
                raise ValueError("Exact signed reply required")
            payload = envelope.result
            require_observation_reply(command, payload)
            if len(canonical(envelope.model_dump(mode="json", exclude_unset=True))) > 1_048_576:
                raise ValueError("Bounded reply required")
            proof = envelope.proof
            now = int(time.time())
            if (
                proof.node_uuid != command.node_uuid
                or proof.operation_uuid != command.operation_uuid
                or proof.status_code != status
                or proof.issued_at > now + 5
                or proof.expires_at <= now
                or not 0 < proof.expires_at - proof.issued_at <= 15
                or proof.issued_at < command.issued_at - 5
                or command.expires_at <= now
                or proof.request_digest != hashlib.sha256(command.signing_bytes()).hexdigest()
                or proof.response_digest
                != hashlib.sha256(
                    canonical(payload.model_dump(mode="json", exclude_unset=True))
                ).hexdigest()
            ):
                raise ValueError("Wrong or stale node reply")
            signature = envelope.signature
            if not isinstance(signature, str):
                raise ValueError("Bounded signature required")
            if len(signature) > 128:
                raise ValueError("Bounded signature required")
            self.key.verify(base64.b64decode(signature, validate=True), proof.signing_bytes())
            return payload.observation()
        except (ValueError, TypeError, InvalidSignature):
            raise ReplyRejected("Node reply not authenticated") from None
