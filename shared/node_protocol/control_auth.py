"""Operation-bound service signatures, separate from Rauthy human identities."""

from __future__ import annotations

import base64
import time
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .control import ControlCommand


class ControlRejected(ValueError):
    pass


class CoreVerifier:
    def __init__(self, public_key: bytes, node_uuid: UUID) -> None:
        key = serialization.load_pem_public_key(public_key)
        if not isinstance(key, Ed25519PublicKey):
            raise ControlRejected("Pinned Core Ed25519 public key required")
        self.key, self.node_uuid = key, node_uuid

    def verify(self, raw: bytes, signature: str) -> ControlCommand:
        if not 0 < len(raw) <= 65_536 or not 1 <= len(signature) <= 128:
            raise ControlRejected("Bounded signed command required")
        try:
            command = ControlCommand.model_validate_json(raw)
            now = int(time.time())
            if (
                command.node_uuid != self.node_uuid
                or command.issued_at > now + 5
                or command.expires_at <= now
            ):
                raise ValueError("Stale or wrong-node command")
            decoded = base64.b64decode(signature, validate=True)
            if len(decoded) != 64:
                raise ValueError("Invalid signature size")
            self.key.verify(decoded, command.signing_bytes())
            return command
        except (ValueError, InvalidSignature):
            raise ControlRejected("Service command not authenticated") from None
