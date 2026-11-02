"""Finite control ports: configuration and observations, with native effects forbidden."""

import asyncio
from dataclasses import dataclass, field
from uuid import UUID

from node_agent.planner import Instance

from node_protocol import NodeRecord
from node_protocol.control import ControlCommand
from node_protocol.journal import JournalOperation
from node_protocol.runtime import validate_node_budget


@dataclass
class ControlRuntimeFixture:
    record: NodeRecord
    instances: list[Instance] = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def node(self) -> NodeRecord:
        return self.record

    def configure(self, record: NodeRecord) -> None:
        self.record = record

    def validate_budget(self, record: NodeRecord, provisioned: NodeRecord) -> None:
        validate_node_budget(record.budget, provisioned.budget)

    async def verify_rootless(self) -> None:
        pass

    async def observed(self) -> list[Instance]:
        return list(self.instances)

    async def observe_completion(self, operation: UUID, sequence: int) -> JournalOperation | None:
        del operation, sequence
        raise AssertionError("Configuration must not schedule or repair native effects")


class NoEffectsScheduler:
    def draining(self) -> bool:
        return False

    def active(self, operation: UUID) -> bool:
        del operation
        return False

    def full(self) -> bool:
        return False

    def schedule(self, command: ControlCommand) -> None:
        del command
        raise AssertionError("Configuration must not schedule native effects")

    def watch_lease(self) -> None:
        pass
