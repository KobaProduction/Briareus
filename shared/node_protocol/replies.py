"""Verify a node reply against an independently pinned public service key."""
import base64
import hashlib
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .control import ControlCommand, ReplyProof, canonical


class ReplyRejected(ValueError):
    pass


class NodeReplyVerifier:
    def __init__(self, public_key: bytes):
        key = serialization.load_pem_public_key(public_key)
        if not isinstance(key, Ed25519PublicKey):
            raise ReplyRejected("Pinned node Ed25519 public key required")
        self.key = key

    def verify(self, command: ControlCommand, status: int, envelope: dict) -> dict:
        try:
            if not isinstance(envelope, dict) or set(envelope) != {"result", "proof", "signature"}:
                raise ValueError("Exact signed reply required")
            payload = envelope["result"]
            if not isinstance(payload, dict) or len(canonical(envelope)) > 1_048_576:
                raise ValueError("Bounded reply required")
            proof = ReplyProof.model_validate(envelope["proof"])
            now = int(time.time())
            if (proof.node_uuid != command.node_uuid or proof.operation_uuid != command.operation_uuid
                or proof.status_code != status or proof.issued_at > now + 5
                or proof.expires_at <= now or not 0 < proof.expires_at - proof.issued_at <= 15
                or proof.issued_at < command.issued_at - 5 or command.expires_at <= now
                or proof.request_digest != hashlib.sha256(command.signing_bytes()).hexdigest()
                or proof.response_digest != hashlib.sha256(canonical(payload)).hexdigest()):
                raise ValueError("Wrong or stale node reply")
            signature = envelope["signature"]
            if not isinstance(signature, str) or len(signature) > 128:
                raise ValueError("Bounded signature required")
            self.key.verify(base64.b64decode(signature, validate=True), proof.signing_bytes())
            return payload
        except (ValueError, TypeError, InvalidSignature):
            raise ReplyRejected("Node reply not authenticated") from None
