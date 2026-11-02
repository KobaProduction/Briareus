"""Project fresh Docker process state and complete placement inventory."""

from typing import Protocol

from node_agent.docker_engine import DockerEngine
from node_agent.domain.readiness import ProcessState
from node_agent.planner import Instance

from .container_models import InspectedState
from .placement import _ControllerBinding
from .process_state import process_state


class NativeReadinessController(Protocol):
    @property
    def engine(self) -> DockerEngine: ...

    async def observed(self) -> list[Instance]: ...


class ControllerReadinessRuntime(_ControllerBinding[NativeReadinessController]):
    async def state(self, container: str) -> ProcessState:
        current = await self._controller.engine.inspect(container)
        return process_state(current.state if current is not None else InspectedState())

    async def complete(self, container: str) -> bool:
        candidates = [
            item for item in await self._controller.observed() if item.container_id == container
        ]
        return len(candidates) == 1 and candidates[0].ready
