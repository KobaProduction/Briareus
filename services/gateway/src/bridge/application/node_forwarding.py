"""Order placement lookup, exact effect authorization, and signed forwarding."""

from collections.abc import Callable
from typing import Protocol
from uuid import UUID

from bridge.domain.admission import ConnectionAdmission, McpAdmission
from bridge.domain.node_forwarding import (
    EffectBinding,
    NodePlacement,
    PreparedForward,
    VerifiedEffect,
    require_effect_binding,
)


class NodeRoutes(Protocol):
    async def resolve(self, *, project_uuid: UUID, module: str) -> NodePlacement: ...


class NodeEffects(Protocol):
    async def authorize(
        self, admission: ConnectionAdmission, route: NodePlacement, body: bytes, request_uuid: UUID
    ) -> VerifiedEffect: ...


class ForwardSigner(Protocol):
    def sign(
        self,
        admission: ConnectionAdmission,
        route: NodePlacement,
        effect: VerifiedEffect,
        *,
        now: int,
        protocol_version: str,
        mcp_session_id: str,
    ) -> PreparedForward: ...


class NodeForwardingPort(Protocol):
    async def prepare(
        self,
        admission: McpAdmission,
        body: bytes,
        *,
        protocol_version: str = "",
        mcp_session_id: str = "",
    ) -> PreparedForward: ...


class PrepareNodeCall:
    def __init__(
        self,
        routes: NodeRoutes,
        effects: NodeEffects,
        signer: ForwardSigner,
        *,
        origins: frozenset[str],
        clock: Callable[[], int],
        digest: Callable[[bytes], str],
        operation_request: Callable[[bytes], UUID],
    ) -> None:
        self.routes, self.effects, self.signer = routes, effects, signer
        self.origins, self.clock, self.digest = origins, clock, digest
        self.operation_request = operation_request

    async def execute(
        self,
        admission: ConnectionAdmission,
        body: bytes,
        *,
        protocol_version: str,
        mcp_session_id: str,
    ) -> PreparedForward:
        route = await self.routes.resolve(
            project_uuid=admission.project_uuid, module=admission.hand
        )
        route.require_current(admission, self.origins, self.clock())
        request_uuid = self.operation_request(body)
        effect = await self.effects.authorize(admission, route, body, request_uuid)
        expected = EffectBinding(
            route.node_uuid,
            route.placement_uuid,
            route.project_uuid,
            route.module,
            route.fingerprint,
            admission.agent_session_uuid,
            admission.grant_revision,
            request_uuid,
            self.digest(body),
            self.digest(admission.bearer.encode()),
            effect.binding.context_digest,
        )
        require_effect_binding(effect.binding, expected)
        now = self.clock()
        if route.expires_at <= now:
            raise ValueError("Node route expired during authorization")
        return self.signer.sign(
            admission,
            route,
            effect,
            now=now,
            protocol_version=protocol_version,
            mcp_session_id=mcp_session_id,
        )
