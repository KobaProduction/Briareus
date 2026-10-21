"""Bounded service-control wire format, shared without cross-service imports."""
import json
from typing import Literal

from pydantic import Field, UUID4, model_validator

from .models import Contract, Deployment, NodeRecord

DOMAIN = b"briareus:node-control\x00"
REPLY_DOMAIN = b"briareus:node-reply\x00"


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode()


class ControlCommand(Contract):
    node_uuid: UUID4
    operation_uuid: UUID4
    action: Literal["apply", "status", "inventory", "configure", "watch"]
    sequence: int = Field(strict=True, ge=1, lt=2**63)
    issued_at: int = Field(strict=True, ge=1)
    expires_at: int = Field(strict=True, ge=1)
    deployment: Deployment | None = None
    node_record: NodeRecord | None = None
    after_event: int = Field(default=0, strict=True, ge=0, lt=2**63)

    @model_validator(mode="after")
    def exact_action(self):
        if self.after_event and self.action != "watch":
            raise ValueError("Only event subscription carries a cursor")
        if (self.action == "apply") != (self.deployment is not None):
            raise ValueError("Only apply carries a deployment")
        if (self.action == "configure") != (self.node_record is not None):
            raise ValueError("Only configure carries node configuration")
        if self.deployment and self.deployment.node_uuid != self.node_uuid:
            raise ValueError("Node and placement identity differ")
        if self.node_record and self.node_record.id != self.node_uuid:
            raise ValueError("Node configuration belongs to another enrollment")
        if not 0 < self.expires_at - self.issued_at <= 60:
            raise ValueError("Bounded service delegation lifetime required")
        return self

    def signing_bytes(self) -> bytes:
        return DOMAIN + canonical(self.model_dump(mode="json"))


class ReplyProof(Contract):
    node_uuid: UUID4
    operation_uuid: UUID4
    request_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    response_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    status_code: int = Field(strict=True, ge=100, le=599)
    issued_at: int = Field(strict=True, ge=1)
    expires_at: int = Field(strict=True, ge=1)

    def signing_bytes(self) -> bytes:
        return REPLY_DOMAIN + canonical(self.model_dump(mode="json"))
