"""Adapt the local journal and current native inventory to receipt recovery."""

from typing import Protocol
from uuid import UUID

from node_agent.application.completion import CompletionCandidate
from node_agent.domain.inventory import ObservedPlacement
from node_agent.domain.placement import OperationConflict
from node_agent.domain.planning import PlanningNode
from node_agent.planner import Instance, observations, planning_node, planning_target
from node_protocol import NodeRecord

from .placement import NativeJournal as NativeJournal
from .placement import NativePlacementEngine, _ControllerBinding, _JournalBinding


class JournalCompletionStore(_JournalBinding):
    async def candidate(self, operation: UUID) -> CompletionCandidate | None:
        row = await self._journal.get(operation)
        if row is None:
            return None
        desired = row.desired
        return CompletionCandidate(row.sequence, row.phase, planning_target(desired), row.container)

    async def complete(self, operation: UUID, container: str) -> None:
        row = await self._journal.get(operation)
        if row is None:
            raise OperationConflict("Operation not found")
        await self._journal.applied(operation, row.desired, container)


class NativeCompletionController(Protocol):
    @property
    def node(self) -> NodeRecord: ...

    @property
    def engine(self) -> NativePlacementEngine: ...

    async def observed(self) -> list[Instance]: ...


class ControllerCompletionRuntime(_ControllerBinding[NativeCompletionController]):
    def node(self) -> PlanningNode:
        return planning_node(self._controller.node)

    async def verify_rootless(self) -> None:
        await self._controller.engine.verify_rootless()

    async def observed(self) -> tuple[ObservedPlacement, ...]:
        return observations(await self._controller.observed())
