"""Dispatch authenticated control requests and sign the resulting Node facts."""

import httpx

from node_agent.application.browser_observation import ObserveBrowser
from node_agent.application.control import NodeControl
from node_agent.application.control_results import reject
from node_agent.identity import NodeIdentity
from node_agent.journal import Journal, JournalUnavailable, OperationConflict
from node_protocol.control import ControlCommand

from .control_wire import SignedControlReply


class ControlEndpoint:
    def __init__(
        self,
        identity: NodeIdentity | None,
        journal: Journal,
        service: NodeControl,
        observer: ObserveBrowser | None,
    ) -> None:
        self._identity, self._journal = identity, journal
        self._service, self._observer = service, observer

    async def __call__(
        self,
        command: ControlCommand,
        core_signature: str = "",
    ) -> tuple[int, SignedControlReply]:
        if self._identity is None:
            raise JournalUnavailable("Node identity unavailable")
        try:
            with self._journal.authority(command, core_signature):
                if command.action == "observe_browser":
                    result = (
                        await self._observer.execute(command, core_signature)
                        if self._observer
                        else reject(
                            503,
                            "BROWSER_OBSERVATION_UNAVAILABLE",
                        )
                    )
                else:
                    result = await self._service.execute(command)
        except (JournalUnavailable, OperationConflict, ValueError, httpx.HTTPError):
            result = reject(503, "NODE_RUNTIME_UNAVAILABLE")
        return result.status, self._identity.reply(command, result.status, result.payload)
