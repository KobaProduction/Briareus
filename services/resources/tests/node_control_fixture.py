"""Finite Node control fixture; no RPC or implicit fallback to live transport."""

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import override
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from projects.application.node_control import NodeControlAction
from projects.node_control import NodeControl

from node_protocol import Deployment, NodeRecord
from node_protocol.domain.observations import NodeEvent, NodeReply


@dataclass(frozen=True)
class ControlCall:
    node_uuid: UUID
    operation_uuid: UUID
    sequence: int
    action: NodeControlAction
    record: NodeRecord | None
    deployment: Deployment | None


class ControlFixture(NodeControl):
    def __init__(self, respond: Callable[[ControlCall], NodeReply]) -> None:
        super().__init__(Ed25519PrivateKey.generate(), frozenset())
        self.respond = respond
        self.calls: list[ControlCall] = []

    @override
    async def call(
        self,
        *,
        endpoint: str,
        public_key: str,
        node_uuid: UUID,
        operation_uuid: UUID,
        sequence: int,
        action: NodeControlAction = "inventory",
        record: NodeRecord | None = None,
        deployment: Deployment | None = None,
    ) -> NodeReply:
        if not endpoint or not public_key:
            raise AssertionError("Pinned Node endpoint required")
        call = ControlCall(node_uuid, operation_uuid, sequence, action, record, deployment)
        self.calls.append(call)
        return self.respond(call)

    @override
    def watch(
        self,
        *,
        endpoint: str,
        public_key: str,
        node_uuid: UUID,
        operation_uuid: UUID,
        sequence: int,
        after_event: int = 0,
    ) -> AsyncIterator[NodeEvent]:
        raise AssertionError("This fixture must terminate through its operation receipt")
