"""Dispatch committed placement intent once, then observe signed operation evidence."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID, uuid4

from node_protocol import Deployment, ModuleRelease
from node_protocol.domain.observations import NodeInventory, NodeOperation, NodeReply
from projects.application.node_control import NodeExecutionControl, NodeUnavailable
from projects.application.placement_listing import PlacementOperationView
from projects.domain.module_catalog import ArtifactDefinition

type SavePlacementReceipt = Callable[[NodeReply, NodeReply | None], Awaitable[bool]]


@dataclass(frozen=True)
class PlacementWriteOutcome:
    operation: PlacementOperationView
    dispatch: bool


@dataclass(frozen=True)
class PlacementExecutionTarget:
    endpoint: str
    public_key: str
    sequence: int
    deployment: Deployment


@dataclass(frozen=True)
class ApprovedPlacementRelease:
    id: UUID
    spec: ModuleRelease
    definition: ArtifactDefinition


@dataclass(frozen=True)
class PlacementCreationIntent:
    operation_uuid: UUID
    actor_uuid: UUID
    name: str
    release_uuid: UUID
    intent_digest: str
    deployment: Deployment


class ReconcilePlacement:
    def __init__(
        self,
        remote: NodeExecutionControl,
        target: PlacementExecutionTarget,
        operation_uuid: UUID,
        save: SavePlacementReceipt,
    ) -> None:
        self.remote, self.target = remote, target
        self.operation_uuid, self.save = operation_uuid, save

    async def _save_receipt(self, payload: NodeReply) -> bool:
        # A failed receipt cannot prove the retained worker is usable. Only a
        # separate signed inventory can authorize restoration of that projection.
        inventory = None
        if (
            isinstance(payload, NodeOperation)
            and payload.phase == "failed"
            and payload.error == "UPDATE_FAILED"
        ):
            try:
                target = self.target
                inventory = await self.remote.call(
                    endpoint=target.endpoint,
                    public_key=target.public_key,
                    node_uuid=target.deployment.node_uuid,
                    sequence=target.sequence,
                    operation_uuid=uuid4(),
                )
            except NodeUnavailable:
                pass
        return await self.save(payload, inventory)

    async def execute(self, *, dispatch: bool) -> None:
        target = self.target
        if dispatch:
            receipt = await self.remote.call(
                endpoint=target.endpoint,
                public_key=target.public_key,
                node_uuid=target.deployment.node_uuid,
                sequence=target.sequence,
                operation_uuid=self.operation_uuid,
                action="apply",
                deployment=target.deployment,
            )
            if await self._save_receipt(receipt):
                return
        inventory = await self.remote.call(
            endpoint=target.endpoint,
            public_key=target.public_key,
            node_uuid=target.deployment.node_uuid,
            sequence=target.sequence,
            operation_uuid=uuid4(),
        )
        if not isinstance(inventory, NodeInventory):
            raise ValueError("Signed inventory cursor required")
        cursor = inventory.event_cursor
        status = await self.remote.call(
            endpoint=target.endpoint,
            public_key=target.public_key,
            node_uuid=target.deployment.node_uuid,
            sequence=target.sequence,
            operation_uuid=self.operation_uuid,
            action="status",
        )
        if not await self._save_receipt(status):
            await self._watch(cursor)

    async def _watch(self, cursor: int) -> None:
        target = self.target
        async with asyncio.timeout(240):
            while True:
                async for event in self.remote.watch(
                    endpoint=target.endpoint,
                    public_key=target.public_key,
                    node_uuid=target.deployment.node_uuid,
                    sequence=target.sequence,
                    operation_uuid=uuid4(),
                    after_event=cursor,
                ):
                    cursor = event.cursor
                    if (
                        event.topic == "operation"
                        and isinstance(event.payload, NodeOperation)
                        and event.payload.operation_uuid == self.operation_uuid
                        and await self._save_receipt(event.payload)
                    ):
                        return
