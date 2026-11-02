"""Dispatch an exact engine selector without owning an MCP client or process."""

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from reverse_hand.domain.dispatch import (
    AnalysisRequest,
    Engine,
    EngineCatalogue,
    EngineCommand,
)


@dataclass(frozen=True, slots=True)
class RejectedResult:
    reason: str


class EngineExecution[ResultT](Protocol):
    def catalogue(self, engine: Engine) -> ResultT: ...
    async def invoke(self, command: EngineCommand, deadline: int | None) -> ResultT: ...


class _DispatchBinding[ExecutionT]:
    def __init__(
        self,
        catalogues: Mapping[Engine, EngineCatalogue],
        execution: ExecutionT,
        now: Callable[[], float],
        long_timeout: float | None,
    ) -> None:
        self._catalogues = catalogues
        self._execution = execution
        self._now = now
        self._long_timeout = long_timeout


class DispatchAnalysis[ResultT](_DispatchBinding[EngineExecution[ResultT]]):
    async def execute(self, request: AnalysisRequest) -> ResultT | RejectedResult:
        try:
            command = request.command
            catalogue = self._catalogues[command.engine]
            command.require_available(catalogue)
            timeout = (
                self._long_timeout
                if request.long_operation
                else max(0, request.expires_at - self._now())
            )
            async with asyncio.timeout(timeout):
                if command.tool is None:
                    return self._execution.catalogue(catalogue.engine)
                deadline = None if request.long_operation else request.expires_at
                return await self._execution.invoke(command, deadline)
        except TimeoutError:
            # Cancellation is not proof that native effects stopped; the parent kills the cohort.
            raise
        except Exception:
            return RejectedResult("REVERSE_OPERATION_REJECTED_OR_UNAVAILABLE")
