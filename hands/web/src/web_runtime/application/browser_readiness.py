"""Probe readiness in order and revoke developer connectivity when CDP is unavailable."""

from dataclasses import dataclass
from typing import Protocol

from web_runtime.domain.browser_readiness import BrowserReadiness


class BrowserReadinessProbe(Protocol):
    def status_needs_start(self) -> bool: ...
    async def start_status_runtime(self) -> None: ...
    def status_process_running(self) -> bool: ...
    async def _cdp_reachable(self) -> bool: ...
    async def _context_usable(self) -> bool: ...
    def status_disconnect_developer(self) -> None: ...


@dataclass(frozen=True)
class ObserveBrowserReadiness:
    probe: BrowserReadinessProbe

    async def execute(self) -> BrowserReadiness:
        if self.probe.status_needs_start():
            await self.probe.start_status_runtime()
        process = self.probe.status_process_running()
        cdp = process and await self.probe._cdp_reachable()
        context = cdp and await self.probe._context_usable()
        if not cdp:
            self.probe.status_disconnect_developer()
        return BrowserReadiness(process, cdp, context)
