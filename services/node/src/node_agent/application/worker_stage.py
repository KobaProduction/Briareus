"""Stage one authorized placement, preserving exact applied recovery and compensation."""

from typing import Protocol

from node_agent.domain.worker_stage import WorkerCandidate, WorkerStageFailure, select_candidate


class WorkerStagePort(Protocol):
    async def prepare_networks(self) -> None: ...

    async def candidates(self) -> tuple[WorkerCandidate, ...]: ...

    async def verify_resume(self, container: str) -> None: ...

    async def ensure_companion(self) -> None: ...

    async def create(self) -> str: ...

    async def start(self, container: str, *, existing: bool) -> None: ...

    async def remove(self, container: str) -> None: ...


class StageWorker:
    def __init__(self, runtime: WorkerStagePort, *, needs_companion: bool) -> None:
        self.runtime, self.needs_companion = runtime, needs_companion

    async def execute(self, *, enabled: bool, gateway_available: bool, resume_stopped: bool) -> str:
        if not enabled:
            raise WorkerStageFailure("Disabled deployment cannot be staged")
        if not gateway_available:
            raise WorkerStageFailure("Private Node Gateway must be provisioned before workers")
        await self.runtime.prepare_networks()
        candidate = select_candidate(await self.runtime.candidates(), resume_stopped=resume_stopped)
        if candidate is not None:
            if candidate.stopped:
                await self.runtime.verify_resume(candidate.identity)
            if self.needs_companion:
                await self.runtime.ensure_companion()
            if candidate.stopped:
                await self.runtime.start(candidate.identity, existing=True)
            return candidate.identity
        container = await self.runtime.create()
        try:
            if self.needs_companion:
                await self.runtime.ensure_companion()
            await self.runtime.start(container, existing=False)
        except WorkerStageFailure:
            # A failed new pair is reaped; retained old candidates are not.
            await self.runtime.remove(container)
            raise
        return container
