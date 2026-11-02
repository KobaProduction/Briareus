"""Compose trusted owner adapters for application Node preparation."""

import time
from collections.abc import Iterable
from typing import Protocol
from uuid import UUID, uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from node_protocol.effect import HumanPermitVerifier
from node_protocol.json_boundary import request_identity
from node_protocol.routing import NodeRoute, NodeRouteReply
from runtime_peer import PeerClient
from runtime_peer.response_decoding import successful_reply

from .application.node_forwarding import PrepareNodeCall
from .domain.admission import HumanAdmission, McpAdmission
from .domain.node_forwarding import NodePlacement, PreparedForward, operation_selector
from .infrastructure.human_web_forwarding import HumanForwarder
from .infrastructure.node_forwarding import (
    AuthorizedNodeEffects,
    EffectAuthority,
    GatewayProofSigner,
    digest,
    placement,
)


def operation_request_uuid(body: bytes) -> UUID:
    """A canonical caller selector confers no authority or replay exemption."""
    frame = request_identity(body)
    selected = operation_selector(frame.method, frame.id)
    return selected if selected is not None else uuid4()


class RouteProjection(Protocol):
    async def resolve(self, *, project_uuid: UUID, module: str) -> NodeRoute: ...


class ResourcesRoutes:
    def __init__(self, peer: PeerClient) -> None:
        self.peer = peer

    async def resolve(self, *, project_uuid: UUID, module: str) -> NodeRoute:
        _owner_reply = await self.peer.call(
            "/internal/v1/resources/node-route",
            {"project_uuid": str(project_uuid), "module": module},
            decode=successful_reply(NodeRouteReply.model_validate),
        )
        status, response = _owner_reply.status, _owner_reply.body
        if status != 200 or response is None:
            raise ValueError("Current Resources placement unavailable")
        return response.route


class CurrentNodeRoutes:
    def __init__(self, routes: RouteProjection) -> None:
        self.routes = routes

    async def resolve(self, *, project_uuid: UUID, module: str) -> NodePlacement:
        route = await self.routes.resolve(project_uuid=project_uuid, module=module)
        if not isinstance(route, NodeRoute):
            raise ValueError("Wrong or expired authoritative node route")
        return placement(route)


def current_time() -> int:
    return int(time.time())


class GatewayNodeRouter:
    def __init__(
        self,
        *,
        routes: RouteProjection,
        signing_key: Ed25519PrivateKey,
        allowed_origins: Iterable[str],
        effect_authority: EffectAuthority | None = None,
        human_verifier: HumanPermitVerifier | None = None,
    ) -> None:
        if not isinstance(signing_key, Ed25519PrivateKey):
            raise ValueError("Explicit Gateway Ed25519 identity required")
        self.routes, self.key, self.allowed_origins = (
            routes,
            signing_key,
            frozenset(allowed_origins),
        )
        self.effect_authority = effect_authority
        self.human_verifier = human_verifier

    async def prepare(
        self,
        admission: McpAdmission,
        body: bytes,
        *,
        protocol_version: str = "",
        mcp_session_id: str = "",
    ) -> PreparedForward:
        if isinstance(admission, HumanAdmission):
            if self.human_verifier is None:
                raise ValueError("Pinned human Web verifier unavailable")
            return await HumanForwarder(
                CurrentNodeRoutes(self.routes),
                self.human_verifier,
                self.key,
                self.allowed_origins,
            ).prepare(
                admission, body, protocol_version=protocol_version, mcp_session_id=mcp_session_id
            )
        use_case = PrepareNodeCall(
            CurrentNodeRoutes(self.routes),
            AuthorizedNodeEffects(self.effect_authority),
            GatewayProofSigner(self.key),
            origins=self.allowed_origins,
            clock=current_time,
            digest=digest,
            operation_request=operation_request_uuid,
        )
        return await use_case.execute(
            admission, body, protocol_version=protocol_version, mcp_session_id=mcp_session_id
        )
