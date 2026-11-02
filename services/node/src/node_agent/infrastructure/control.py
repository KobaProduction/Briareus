"""Connect admitted control use cases to the existing native controller."""

import asyncio
from uuid import UUID

from node_agent.controller import Controller
from node_agent.planner import Instance as Instance
from node_protocol import NodeRecord
from node_protocol.journal import JournalOperation
from node_protocol.runtime import validate_node_budget

from .placement import _ControllerObservations, translate_failure


class ControllerControlRuntime(_ControllerObservations[Controller]):
    @property
    def lock(self) -> asyncio.Lock:
        return self._controller.lock

    def node(self) -> NodeRecord:
        return self._controller.node

    def configure(self, record: NodeRecord) -> None:
        self._controller.node = record

    def validate_budget(self, record: NodeRecord, provisioned: NodeRecord) -> None:
        validate_node_budget(record.budget, provisioned.budget)

    async def observe_completion(self, operation: UUID, sequence: int) -> JournalOperation | None:
        with translate_failure():
            return await self._controller.observe_completion(operation, sequence)
