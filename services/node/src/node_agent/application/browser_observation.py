"""Observe an admitted browser placement without execution admission or scheduling."""

import time
from typing import Protocol

from node_protocol.browser_observation import BrowserObservationSelector
from node_protocol.control import ControlCommand
from node_protocol.domain.browser_observation import NodeBrowserObservation

from .control_results import ControlResult, reject


class BrowserObservationPort(Protocol):
    async def current(self, selector: BrowserObservationSelector) -> bool: ...
    async def read(self, command: ControlCommand, signature: str) -> NodeBrowserObservation: ...


class ObserveBrowser:
    def __init__(self, port: BrowserObservationPort) -> None:
        self._port = port

    async def execute(self, command: ControlCommand, signature: str) -> ControlResult:
        target = command.browser_observation
        if command.action != "observe_browser" or target is None or not signature:
            return reject(403, "BROWSER_OBSERVATION_DENIED")
        if command.expires_at <= time.time() or not await self._port.current(target):
            return reject(503, "BROWSER_OBSERVATION_UNAVAILABLE")
        observed = await self._port.read(command, signature)
        if (
            observed.target != target.observation()
            or command.expires_at <= time.time()
            or not await self._port.current(target)
        ):
            return reject(503, "BROWSER_OBSERVATION_UNAVAILABLE")
        return ControlResult(200, observed)
