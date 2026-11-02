"""Execution-control transport port, independent of gRPC and SQL persistence."""

from collections.abc import AsyncIterator
from typing import Literal, Protocol
from uuid import UUID

from node_protocol import Deployment, NodeRecord
from node_protocol.domain.observations import NodeEvent, NodeReply

type NodeControlAction = Literal["inventory", "configure", "apply", "status"]


class NodeUnavailable(ValueError):
    """The execution peer could not provide authenticated evidence."""


class NodeExecutionControl(Protocol):
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
    ) -> NodeReply: ...

    def watch(
        self,
        *,
        endpoint: str,
        public_key: str,
        node_uuid: UUID,
        operation_uuid: UUID,
        sequence: int,
        after_event: int = 0,
    ) -> AsyncIterator[NodeEvent]: ...

    async def close(self) -> None: ...
