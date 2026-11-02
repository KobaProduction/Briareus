"""Repair a lost receipt from fresh inventory without replaying native effects."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from node_agent.domain.inventory import ObservedPlacement
from node_agent.domain.planning import PlanningNode, PlanningTarget, completion_matches


@dataclass(frozen=True, slots=True)
class CompletionCandidate:
    sequence: int
    phase: str
    target: PlanningTarget
    container: str | None


class CompletionStore(Protocol):
    async def candidate(self, operation: UUID) -> CompletionCandidate | None: ...

    async def complete(self, operation: UUID, container: str) -> None: ...


class CompletionRuntime(Protocol):
    def node(self) -> PlanningNode: ...

    async def verify_rootless(self) -> None: ...

    async def observed(self) -> tuple[ObservedPlacement, ...]: ...


class ObserveCompletion:
    def __init__(self, store: CompletionStore, runtime: CompletionRuntime) -> None:
        self._store, self._runtime = store, runtime

    async def execute(self, operation: UUID, sequence: int) -> None:
        candidate = await self._store.candidate(operation)
        if candidate is None or candidate.sequence != sequence or candidate.phase != "checking":
            return
        node = self._runtime.node()
        if (
            not node.enabled
            or not candidate.target.enabled
            or candidate.target.node_uuid != node.node_uuid
        ):
            return
        await self._runtime.verify_rootless()
        observed = await self._runtime.observed()
        if candidate.container is not None and completion_matches(
            candidate.target,
            candidate.container,
            observed,
            node,
        ):
            # completion_matches proves the unique exact candidate, not merely
            # a healthy process with familiar labels.
            await self._store.complete(operation, candidate.container)
