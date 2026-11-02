"""Authorization-owned short-lived execution evidence, separate from OAuth identity."""

import base64
import hashlib
import logging
import time
from typing import Literal
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import UUID4, Field

from .control import canonical
from .domain.effect_authority import EffectAuthority, EffectBinding, EffectRequest
from .json_boundary import decode_json
from .models import Contract, Deployment

LOG = logging.getLogger(__name__)
DOMAIN = b"briareus:node-effect-permit\0"


class NodeWorkspaceBinding(Contract):
    node_uuid: UUID4
    placement_uuid: UUID4
    project_uuid: UUID4
    workspace_uuid: UUID4
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    resource_id: str = Field(min_length=80, max_length=256)
    effect_verify_key: str = Field(min_length=80, max_length=256)
    resource_revision: int = Field(strict=True, ge=1, lt=2**63)
    expires_at: int = Field(strict=True, ge=1)


class NodeWorkspaceReply(Contract):
    binding: NodeWorkspaceBinding


class ResourceEffectPermit(Contract):
    module: Literal["files", "terminal", "web", "svc", "infrastructure", "reverse", "serena"] = (
        Field(default="files", exclude_if=lambda value: value == "files")
    )
    context_digest: str = Field(
        default="", pattern=r"^(?:[a-f0-9]{64})?$", exclude_if=lambda value: value == ""
    )
    node_uuid: UUID4
    placement_uuid: UUID4
    project_uuid: UUID4
    workspace_uuid: UUID4
    actor_uuid: UUID4
    request_uuid: UUID4
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    body_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    bearer_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    arguments_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    method: Literal["initialize", "notifications/initialized", "ping", "tools/list", "tools/call"]
    tool: str | None = Field(max_length=128)
    resource_id: str = Field(min_length=80, max_length=256)
    issued_at: int = Field(strict=True, ge=1)
    expires_at: int = Field(strict=True, ge=1)

    def signing_bytes(self) -> bytes:
        # Existing immutable Files releases keep their exact signed contract.
        # Terminal evidence always carries its distinct execution module.
        return DOMAIN + canonical(self.model_dump(mode="json"))

    def authority(self) -> EffectAuthority:
        return EffectAuthority(
            EffectBinding(
                self.node_uuid,
                self.placement_uuid,
                self.project_uuid,
                self.workspace_uuid,
                self.fingerprint,
                self.module,
                self.resource_id,
            ),
            EffectRequest(
                self.method,
                self.tool,
                self.arguments_digest,
                self.body_digest,
                self.bearer_digest,
            ),
            self.issued_at,
            self.expires_at,
        )


class NodeEffectPermit(ResourceEffectPermit):
    agent_session_uuid: UUID4
    grant_revision: int = Field(strict=True, ge=1, lt=2**63)


class HumanEffectPermit(ResourceEffectPermit):
    """Authorization-issued human authority, independently of agent grants."""

    human: Literal[True]
    module: Literal["web", "files", "terminal", "reverse"]
    resource_revision: int = Field(strict=True, ge=1, lt=2**63)


type EffectPermit = NodeEffectPermit | HumanEffectPermit


class SignedEffectPermit(Contract):
    permit: EffectPermit
    signature: str


def sign_permit(permit: EffectPermit, key: Ed25519PrivateKey) -> str:
    envelope = SignedEffectPermit(
        permit=permit,
        signature=base64.b64encode(key.sign(permit.signing_bytes())).decode(),
    )
    return base64.b64encode(canonical(envelope.model_dump(mode="json"))).decode()


class EffectRejected(ValueError):
    pass


class HumanPermitVerifier:
    """Verify Core evidence before any caller may select human execution."""

    def __init__(self, public_key: bytes) -> None:
        key = serialization.load_pem_public_key(public_key)
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError("Pinned Authorization Ed25519 public key required")
        self.key = key

    def verify(
        self, encoded: str, *, body: bytes, bearer: str, project_uuid: UUID
    ) -> HumanEffectPermit:
        try:
            if not 0 < len(encoded) <= 8192:
                raise ValueError("Bounded human authority required")
            envelope = decode_json(base64.b64decode(encoded, validate=True), SignedEffectPermit)
            permit = envelope.permit
            self.key.verify(
                base64.b64decode(envelope.signature, validate=True), permit.signing_bytes()
            )
            if not isinstance(permit, HumanEffectPermit) or permit.project_uuid != project_uuid:
                raise ValueError("Wrong human authority")
            from .module_effects import parse_request

            parsed = parse_request(permit.module, body)
            request = EffectRequest(
                parsed.method,
                parsed.tool,
                parsed.arguments_digest,
                hashlib.sha256(body).hexdigest(),
                hashlib.sha256(bearer.encode()).hexdigest(),
            )
            permit.authority().require_current(
                permit.authority().binding, request, bearer, int(time.time())
            )
            return permit
        except (ValueError, KeyError, TypeError, InvalidSignature):
            raise EffectRejected("Current human Web authority required") from None


class EffectVerifier:
    def __init__(self, spec: Deployment) -> None:
        from .module_effects import MODULES

        if (
            spec.workspace is None
            or spec.release.module not in MODULES
            or not spec.effect_verify_key
        ):
            raise ValueError("Bound executor workspace and pinned Authorization key required")
        self.spec = spec
        key = serialization.load_pem_public_key(spec.effect_verify_key.encode())
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError("Authorization Ed25519 public key required")
        self.key = key

    def _binding(self) -> EffectBinding:
        from .module_effects import resource_id

        spec = self.spec
        if spec.workspace is None:
            raise ValueError("Bound executor workspace required")
        return EffectBinding(
            spec.node_uuid,
            spec.id,
            spec.project_uuid,
            spec.workspace.id,
            spec.fingerprint,
            spec.release.module,
            resource_id(spec.release.module, spec.node_uuid, spec.project_uuid, spec.workspace.id),
        )

    def verify(self, encoded: str, *, body: bytes, bearer: str) -> EffectPermit:
        try:
            if not isinstance(encoded, str):
                raise ValueError("Bounded effect evidence required")
            if not 0 < len(encoded) <= 8192:
                raise ValueError("Bounded effect evidence required")
            envelope = decode_json(base64.b64decode(encoded, validate=True), SignedEffectPermit)
            permit = envelope.permit
            self.key.verify(
                base64.b64decode(envelope.signature, validate=True), permit.signing_bytes()
            )
            now = int(time.time())
            from .module_effects import parse_request as parse_module

            parsed = parse_module(self.spec.release.module, body)
            request = EffectRequest(
                parsed.method,
                parsed.tool,
                parsed.arguments_digest,
                hashlib.sha256(body).hexdigest(),
                hashlib.sha256(bearer.encode()).hexdigest(),
            )
            authority = permit.authority()
            binding = self._binding()
            try:
                authority.require_current(binding, request, bearer, now)
            except ValueError:
                LOG.warning(
                    "Effect rejected binding_mismatch=%s request_mismatch=%s "
                    "age=%d remaining=%d window=%d",
                    authority.binding != binding,
                    authority.request != request,
                    now - permit.issued_at,
                    permit.expires_at - now,
                    permit.expires_at - permit.issued_at,
                )
                raise
            return permit
        except (ValueError, KeyError, TypeError, InvalidSignature):
            raise EffectRejected("Current Core Files authority required") from None
