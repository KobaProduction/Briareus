"""Authenticated owner projections and exact Node proof wire encoding."""

import base64
import hashlib
from typing import Protocol
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from bridge.domain.admission import ConnectionAdmission
from bridge.domain.node_forwarding import (
    AuthorityEvidence,
    EffectBinding,
    NodePlacement,
    PreparedForward,
    VerifiedEffect,
    node_module,
)
from node_protocol.effect import NodeEffectPermit, SignedEffectPermit
from node_protocol.forward import ForwardProof
from node_protocol.json_boundary import decode_json
from node_protocol.module_effects import MODULES
from node_protocol.provider_context import InvocationContext
from node_protocol.routing import NodeRoute
from service_runtime._reference_bindings import _KeyBinding


def placement(route: NodeRoute) -> NodePlacement:
    return NodePlacement(
        route.node_uuid,
        route.placement_uuid,
        route.project_uuid,
        node_module(route.module),
        route.fingerprint,
        route.port,
        route.origin,
        route.expires_at,
    )


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def context_digest(context: str) -> str:
    if len(context) > 11000:
        raise ValueError("Bounded private owner context required")
    if not context:
        return ""
    raw = base64.b64decode(context, validate=True)
    if not raw or len(raw) > 8192:
        raise ValueError("Bounded private owner context required")
    decode_json(raw, InvocationContext)
    return digest(raw)


def authority_evidence(value: object) -> AuthorityEvidence:
    if not isinstance(value, dict) or set(value) not in ({"permit"}, {"permit", "context"}):
        raise ValueError("Current exact module effect authority unavailable")
    permit, context = value["permit"], value.get("context", "")
    if not isinstance(permit, str) or not 0 < len(permit) <= 8192 or not isinstance(context, str):
        raise ValueError("Exact private authority evidence required")
    context_digest(context)
    return AuthorityEvidence(permit, context)


class EffectAuthority(Protocol):
    async def authorize_module(
        self,
        *,
        admission: ConnectionAdmission,
        route: NodePlacement,
        body: bytes,
        request_uuid: UUID,
    ) -> AuthorityEvidence: ...


class AuthorizedNodeEffects:
    def __init__(self, authority: EffectAuthority | None) -> None:
        self.authority = authority

    async def authorize(
        self, admission: ConnectionAdmission, route: NodePlacement, body: bytes, request_uuid: UUID
    ) -> VerifiedEffect:
        if route.module not in MODULES or self.authority is None:
            raise ValueError("Current exact module effect authority required")
        evidence = await self.authority.authorize_module(
            admission=admission, route=route, body=body, request_uuid=request_uuid
        )
        if not isinstance(evidence, AuthorityEvidence):
            raise ValueError("Exact private authority evidence required")
        if not 0 < len(evidence.permit) <= 8192:
            raise ValueError("Exact private authority evidence required")
        expected_context = context_digest(evidence.context)
        envelope = decode_json(base64.b64decode(evidence.permit, validate=True), SignedEffectPermit)
        claims = envelope.permit
        if not isinstance(claims, NodeEffectPermit):
            raise ValueError("Agent effect authority required")
        if claims.context_digest != expected_context:
            raise ValueError("Effect authority changed request or credential context")
        # The owner peer authenticates this evidence; the worker independently
        # verifies the effect signature before executing the exact effect.
        binding = EffectBinding(
            claims.node_uuid,
            claims.placement_uuid,
            claims.project_uuid,
            claims.module,
            claims.fingerprint,
            claims.agent_session_uuid,
            claims.grant_revision,
            claims.request_uuid,
            claims.body_digest,
            claims.bearer_digest,
            claims.context_digest,
        )
        return VerifiedEffect(evidence, binding)


class GatewayProofSigner(_KeyBinding[Ed25519PrivateKey]):
    def sign(
        self,
        admission: ConnectionAdmission,
        route: NodePlacement,
        effect: VerifiedEffect,
        *,
        now: int,
        protocol_version: str,
        mcp_session_id: str,
    ) -> PreparedForward:
        binding, evidence = effect.binding, effect.evidence
        proof = ForwardProof(
            node_uuid=route.node_uuid,
            placement_uuid=route.placement_uuid,
            project_uuid=route.project_uuid,
            module=route.module,
            port=route.port,
            fingerprint=route.fingerprint,
            agent_session_uuid=admission.agent_session_uuid,
            request_uuid=binding.request_uuid,
            grant_revision=admission.grant_revision,
            body_digest=binding.body_digest,
            bearer_digest=binding.bearer_digest,
            effect_digest=digest(evidence.permit.encode()),
            context_digest=binding.context_digest,
            protocol_version=protocol_version,
            mcp_session_id=mcp_session_id,
            issued_at=now,
            expires_at=route.expires_at,
        )
        return PreparedForward(
            route.origin + "/internal/v1/node/mcp",
            evidence.permit,
            base64.b64encode(proof.canonical_bytes()).decode(),
            base64.b64encode(self.key.sign(proof.signing_bytes())).decode(),
            evidence.context,
        )
