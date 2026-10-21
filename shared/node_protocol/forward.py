"""Request-bound Gateway transport proof; never a substitute for Cedar grants."""
import base64
import hashlib
import time
from typing import Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import Field, UUID4

from .control import canonical
from .models import Contract

DOMAIN = b"briareus:node-mcp-forward\x00"


class ForwardProof(Contract):
    node_uuid: UUID4
    placement_uuid: UUID4
    project_uuid: UUID4
    agent_session_uuid: UUID4
    request_uuid: UUID4
    grant_revision: int = Field(strict=True, ge=1, lt=2**63)
    module: Literal["files", "terminal", "web", "svc", "infrastructure", "reverse", "serena"]
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    port: int = Field(strict=True, ge=1024, le=65535)
    body_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    bearer_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    effect_digest: str = Field(default="", pattern=r"^(?:[a-f0-9]{64})?$")
    context_digest: str = Field(default="", pattern=r"^(?:[a-f0-9]{64})?$")
    protocol_version: str = Field(default="", max_length=64, pattern=r"^[\x21-\x7e]*$")
    mcp_session_id: str = Field(default="", max_length=256, pattern=r"^[\x21-\x7e]*$")
    issued_at: int = Field(strict=True, ge=1)
    expires_at: int = Field(strict=True, ge=1)

    @property
    def container_name(self):
        from .naming import worker_name
        return worker_name(self.node_uuid,self.placement_uuid,self.fingerprint)

    def wire(self):
        # Existing immutable worker forwarding contracts have no context field.
        return self.model_dump(mode="json", exclude={"context_digest"} if not self.context_digest else set())

    def signing_bytes(self):
        return DOMAIN + canonical(self.wire())


class ForwardRejected(ValueError):
    pass


class ForwardVerifier:
    def __init__(self, public_key: bytes, node_uuid):
        key = serialization.load_pem_public_key(public_key)
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError("Pinned Gateway Ed25519 public key required")
        self.key, self.node_uuid = key, node_uuid

    def verify(self, encoded: str, signature: str, *, body: bytes, bearer: str, effect: str = "", context: str = ""):
        try:
            if len(encoded) > 4096 or len(signature) > 128 or not 0 < len(body) <= 1_048_576:
                raise ValueError("Bounded forwarding request required")
            if not isinstance(context, str) or len(context) > 11000:
                raise ValueError("Bounded private invocation context required")
            context_bytes = base64.b64decode(context, validate=True) if context else b""
            if context and (not context_bytes or len(context_bytes) > 8192):
                raise ValueError("Bounded decoded invocation context required")
            raw = base64.b64decode(encoded, validate=True)
            proof = ForwardProof.model_validate_json(raw)
            now = int(time.time())
            if (proof.node_uuid != self.node_uuid or proof.issued_at > now + 5 or proof.expires_at <= now
                or not 0 < proof.expires_at - proof.issued_at <= 15
                or proof.body_digest != hashlib.sha256(body).hexdigest()
                or proof.bearer_digest != hashlib.sha256(bearer.encode()).hexdigest()
                or proof.context_digest != (hashlib.sha256(context_bytes).hexdigest() if context else "")
                or len(effect) > 8192
                or proof.effect_digest != (hashlib.sha256(effect.encode()).hexdigest() if effect else "")
                or not bearer.startswith("Bearer ") or bearer.count(" ") != 1
                or not 0 < len(bearer) <= 8192):
                raise ValueError("Wrong or stale forwarding request")
            self.key.verify(base64.b64decode(signature, validate=True), proof.signing_bytes())
            return proof
        except (ValueError, InvalidSignature, TypeError):
            raise ForwardRejected("Gateway forwarding proof rejected") from None
