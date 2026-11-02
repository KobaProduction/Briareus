"""Native placement checks and private Gateway reads; no agent grants are touched."""

import httpx

from node_agent.application.control import NodeControl
from node_agent.controller import Controller
from node_protocol.browser_observation import (
    OBSERVATION_PATH,
    BrowserObservationSelector,
    BrowserObservationWire,
)
from node_protocol.browser_observation_request import SignedBrowserObservation
from node_protocol.control import ControlCommand
from node_protocol.domain.browser_observation import NodeBrowserObservation
from node_protocol.json_boundary import decode_json
from node_protocol.naming import worker_name

from .execution_tasks import NodeExecutionTasks
from .forward_admission import private_gateway_socket
from .process_state import process_state


class NativeBrowserObservation:
    def __init__(
        self,
        controller: Controller,
        service: NodeControl,
        tasks: NodeExecutionTasks,
        client: httpx.AsyncClient,
    ) -> None:
        self._controller, self._service = controller, service
        self._tasks, self._client = tasks, client

    def accepting(self) -> bool:
        return self._controller.node.enabled and not self._tasks.draining()

    async def current(self, selector: BrowserObservationSelector) -> bool:
        await self._service.initialize()
        if not self.accepting():
            return False
        await self._controller.engine.verify_rootless()
        found = [
            item
            for item in await self._controller.observed()
            if item.deployment_uuid == selector.placement_uuid
        ]
        if len(found) != 1:
            return False
        item = found[0]
        current = await self._controller.engine.inspect(
            worker_name(
                self._controller.node.id,
                selector.placement_uuid,
                selector.fingerprint,
            )
        )
        if current is None:
            return False
        state = process_state(current.state)
        return (
            self.accepting()
            and item.running
            and item.ready
            and item.fingerprint == selector.fingerprint
            and item.container_id == current.identity
            and state.running is True
            and state.health == "healthy"
        )

    async def read(self, command: ControlCommand, signature: str) -> NodeBrowserObservation:
        private_gateway_socket()
        envelope = SignedBrowserObservation(command=command, signature=signature)
        async with self._client.stream(
            "POST",
            "http://node-gateway" + OBSERVATION_PATH,
            content=envelope.model_dump_json(),
            headers={"content-type": "application/json"},
        ) as response:
            if response.status_code != 200:
                raise ValueError("Browser observation unavailable")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > 1_048_576:
                    raise ValueError("Bounded browser observation required")
        return decode_json(body, BrowserObservationWire).observation()
