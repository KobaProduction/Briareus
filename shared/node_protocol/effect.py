"""Authorization-owned short-lived execution evidence, separate from OAuth identity."""
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
from .files import parse_request, workspace_resource, strict_json

DOMAIN=b"briareus:node-effect-permit\0"


class NodeWorkspaceBinding(Contract):
    node_uuid: UUID4
    placement_uuid: UUID4
    project_uuid: UUID4
    workspace_uuid: UUID4
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    resource_id: str = Field(min_length=80,max_length=256)
    effect_verify_key: str = Field(min_length=80,max_length=256)
    resource_revision: int = Field(strict=True,ge=1,lt=2**63)
    expires_at: int = Field(strict=True,ge=1)


class NodeEffectPermit(Contract):
    module: Literal["files", "terminal", "web", "svc", "infrastructure", "reverse", "serena"] = "files"
    context_digest: str = Field(default="", pattern=r"^(?:[a-f0-9]{64})?$")
    node_uuid: UUID4
    placement_uuid: UUID4
    project_uuid: UUID4
    workspace_uuid: UUID4
    actor_uuid: UUID4
    agent_session_uuid: UUID4
    request_uuid: UUID4
    grant_revision: int = Field(strict=True,ge=1,lt=2**63)
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    body_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    bearer_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    arguments_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    method: Literal["initialize","notifications/initialized","ping","tools/list","tools/call"]
    tool: str | None = Field(max_length=128)
    resource_id: str = Field(min_length=80,max_length=256)
    issued_at: int = Field(strict=True,ge=1)
    expires_at: int = Field(strict=True,ge=1)

    def signing_bytes(self):
        return DOMAIN+canonical(self.wire())

    def wire(self):
        # Existing immutable Files releases keep their exact signed contract.
        # Terminal evidence always carries its distinct execution module.
        excluded = {"module"} if self.module == "files" else set()
        if not self.context_digest:
            excluded.add("context_digest")
        return self.model_dump(mode="json", exclude=excluded)


def sign_permit(permit, key):
    return base64.b64encode(canonical({"permit":permit.wire(),
        "signature":base64.b64encode(key.sign(permit.signing_bytes())).decode()})).decode()


class EffectRejected(ValueError):
    pass


class EffectVerifier:
    def __init__(self,spec):
        from .module_effects import MODULES
        if spec.workspace is None or spec.release.module not in MODULES or not spec.effect_verify_key:
            raise ValueError("Bound executor workspace and pinned Authorization key required")
        self.spec=spec
        self.key=serialization.load_pem_public_key(spec.effect_verify_key.encode())
        if not isinstance(self.key,Ed25519PublicKey):
            raise ValueError("Authorization Ed25519 public key required")

    def verify(self,encoded,*,body,bearer):
        try:
            if not isinstance(encoded,str) or not 0<len(encoded)<=8192:
                raise ValueError("Bounded effect evidence required")
            envelope=strict_json(base64.b64decode(encoded,validate=True))
            if not isinstance(envelope,dict) or set(envelope)!={"permit","signature"}:
                raise ValueError("Exact signed effect envelope required")
            permit=NodeEffectPermit.model_validate(envelope["permit"])
            self.key.verify(base64.b64decode(envelope["signature"],validate=True),permit.signing_bytes())
            now=int(time.time())
            spec=self.spec
            from .module_effects import parse_request as parse_module, resource_id
            parsed = parse_module(spec.release.module, body)
            if (permit.node_uuid!=spec.node_uuid or permit.placement_uuid!=spec.id or permit.project_uuid!=spec.project_uuid
                or permit.workspace_uuid!=spec.workspace.id or permit.fingerprint!=spec.fingerprint
                or permit.module != spec.release.module
                or permit.resource_id!=resource_id(spec.release.module,spec.node_uuid,spec.project_uuid,spec.workspace.id)
                or permit.method!=parsed.method or permit.tool!=parsed.tool
                or permit.arguments_digest!=hashlib.sha256(canonical(parsed.arguments)).hexdigest()
                or permit.body_digest!=hashlib.sha256(body).hexdigest()
                or permit.bearer_digest!=hashlib.sha256(bearer.encode()).hexdigest()
                or not bearer.startswith("Bearer ") or bearer.count(" ")!=1
                or permit.issued_at>now+2 or permit.expires_at<=now
                or not 0<permit.expires_at-permit.issued_at<=5):
                raise ValueError("Wrong or expired effect authority")
            return permit
        except (ValueError,KeyError,TypeError,InvalidSignature):
            raise EffectRejected("Current Core Files authority required") from None
