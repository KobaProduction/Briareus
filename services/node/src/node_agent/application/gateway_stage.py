"""Deliver the new image before replacing a Gateway, then reconnect without worker restarts."""

from typing import Protocol

from node_agent.domain.gateway_stage import GatewayCandidate, gateway_candidate

from ._runtime_binding import _RuntimeBinding


class GatewayStagePort(Protocol):
    def fingerprint(self) -> str: ...
    async def verify(self) -> None: ...
    async def candidates(self) -> tuple[GatewayCandidate, ...]: ...
    async def pull(self) -> None: ...
    async def ensure_ingress(self) -> None: ...
    async def remove(self, container: str) -> None: ...
    async def create(self) -> str: ...
    async def start(self, container: str, *, existing: bool) -> None: ...
    async def reconnect(self, container: str) -> None: ...


class EnsureGateway(_RuntimeBinding[GatewayStagePort]):
    async def execute(self) -> str:
        await self.runtime.verify()
        candidate = gateway_candidate(await self.runtime.candidates())
        if candidate is not None and candidate.fingerprint == self.runtime.fingerprint():
            container = candidate.identity
            if not candidate.running:
                await self.runtime.start(container, existing=True)
        else:
            await self.runtime.pull()
            await self.runtime.ensure_ingress()
            if candidate is not None:
                await self.runtime.remove(candidate.identity)
            container = await self.runtime.create()
            await self.runtime.start(container, existing=False)
        await self.runtime.reconnect(container)
        return container
