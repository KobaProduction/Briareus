"""Select a trusted Resources placement after real Authorization admission."""
import base64
import hashlib
import time
from uuid import UUID, uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from node_protocol.forward import ForwardProof
from node_protocol.module_effects import MODULES
from node_protocol.control import canonical
from node_protocol.files import strict_json


def operation_request_uuid(body):
    """Preserve a caller's canonical operation selector in signed evidence.

    This confers no authority: Core still binds exact bytes, actor, session,
    revision and resource; Node's existing replay fence still rejects repeats.
    A lost start can consequently be polled as request:<original RPC UUID>.
    """
    frame = strict_json(body)
    if frame.get("method") == "tools/call" and isinstance(frame.get("id"), str):
        try:
            selected = UUID(frame["id"])
            if selected.version == 4 and str(selected) == frame["id"]:
                return selected
        except ValueError:
            pass
    return uuid4()
from node_protocol.effect import NodeEffectPermit
from node_protocol.routing import NodeRoute


class ResourcesRoutes:
    def __init__(self, peer):
        self.peer = peer

    async def resolve(self, *, project_uuid, module):
        status, response = await self.peer.call("/internal/v1/resources/node-route",
            {"project_uuid": str(project_uuid), "module": module})
        if status != 200 or not isinstance(response, dict) or set(response) != {"route"}:
            raise ValueError("Current Resources placement unavailable")
        return NodeRoute.model_validate(response["route"])


class GatewayNodeRouter:
    def __init__(self, *, routes, signing_key, allowed_origins, effect_authority=None):
        if not isinstance(signing_key, Ed25519PrivateKey):
            raise ValueError("Explicit Gateway Ed25519 identity required")
        self.routes, self.key, self.allowed_origins = routes, signing_key, frozenset(allowed_origins)
        self.effect_authority = effect_authority

    async def prepare(self, admission, body, *, protocol_version="", mcp_session_id=""):
        route = await self.routes.resolve(project_uuid=admission.project_uuid, module=admission.hand)
        now = int(time.time())
        if (not isinstance(route, NodeRoute) or route.project_uuid != admission.project_uuid
            or route.module != admission.hand or route.origin not in self.allowed_origins
            or not now < route.expires_at <= now + 5):
            raise ValueError("Wrong or expired authoritative node route")
        request_uuid = operation_request_uuid(body)
        if route.module not in MODULES or self.effect_authority is None:
            raise ValueError("Current exact module effect authority required")
        evidence = await self.effect_authority.authorize_module(admission=admission, route=route,
            body=body, request_uuid=request_uuid)
        if (not isinstance(evidence, dict) or set(evidence) != {"permit", "context"}
            or not isinstance(evidence["permit"], str) or not 0 < len(evidence["permit"]) <= 8192
            or not isinstance(evidence["context"], str) or len(evidence["context"]) > 11000):
            raise ValueError("Exact private authority evidence required")
        permit, context = evidence["permit"], evidence["context"]
        raw_context = base64.b64decode(context, validate=True) if context else b""
        if context and (not raw_context or len(raw_context) > 8192 or not isinstance(strict_json(raw_context), dict)):
            raise ValueError("Bounded private owner context required")
        context_digest = hashlib.sha256(raw_context).hexdigest() if context else ""
        # The peer-authenticated Authorization reply must bind this very context;
        # the worker independently verifies the Ed25519 effect signature later.
        envelope = strict_json(base64.b64decode(permit, validate=True))
        if not isinstance(envelope, dict) or set(envelope) != {"permit", "signature"}:
            raise ValueError("Exact signed effect envelope required")
        claims = NodeEffectPermit.model_validate(envelope["permit"])
        if (claims.context_digest != context_digest or claims.module != route.module
            or claims.node_uuid != route.node_uuid or claims.placement_uuid != route.placement_uuid
            or claims.project_uuid != route.project_uuid or claims.fingerprint != route.fingerprint
            or claims.agent_session_uuid != admission.agent_session_uuid
            or claims.grant_revision != admission.grant_revision or claims.request_uuid != request_uuid
            or claims.body_digest != hashlib.sha256(body).hexdigest()
            or claims.bearer_digest != hashlib.sha256(admission.bearer.encode()).hexdigest()):
            raise ValueError("Effect authority changed request or credential context")
        now = int(time.time())
        if route.expires_at <= now:
            raise ValueError("Node route expired during authorization")
        proof = ForwardProof(node_uuid=route.node_uuid, placement_uuid=route.placement_uuid,
            project_uuid=route.project_uuid, module=route.module, port=route.port,
            fingerprint=route.fingerprint, agent_session_uuid=admission.agent_session_uuid,
            request_uuid=request_uuid, grant_revision=admission.grant_revision,
            body_digest=hashlib.sha256(body).hexdigest(),
            bearer_digest=hashlib.sha256(admission.bearer.encode()).hexdigest(),
            effect_digest=hashlib.sha256(permit.encode()).hexdigest(),
            context_digest=context_digest, protocol_version=protocol_version, mcp_session_id=mcp_session_id,
            issued_at=now, expires_at=route.expires_at)
        headers = {
            "x-briareus-node-permit": permit,
            "x-briareus-node-proof": base64.b64encode(canonical(proof.wire())).decode(),
            "x-briareus-node-signature": base64.b64encode(self.key.sign(proof.signing_bytes())).decode()}
        if context:
            headers["x-briareus-invocation-context"] = context
        return route.origin + "/internal/v1/node/mcp", headers
