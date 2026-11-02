"""Wire process startup and shutdown without terminating persistent placements."""

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from cryptography.hazmat.primitives import serialization
from starlette.applications import Starlette

from node_agent.control_auth import CoreVerifier
from node_agent.dataplane import McpRelay
from node_agent.docker_engine import DockerEngine
from node_agent.grpc_server import ControlHandler, start_server
from node_agent.identity import NodeIdentity
from node_agent.journal import Journal
from node_protocol import NodeRecord

from .execution_tasks import NodeExecutionTasks
from .forward_admission import private_gateway_socket


class NodeLifespan:
    def __init__(
        self,
        *,
        node: NodeRecord,
        engine: DockerEngine,
        journal: Journal,
        tasks: NodeExecutionTasks,
        relay: McpRelay | None,
        verifier: CoreVerifier,
        identity: NodeIdentity | None,
        handler: ControlHandler,
        gateway_image: str | None,
        grpc_bind: str | None,
    ) -> None:
        self._node, self._engine, self._journal = node, engine, journal
        self._tasks, self._relay, self._verifier = tasks, relay, verifier
        self._identity, self._handler = identity, handler
        self._gateway_image, self._grpc_bind = gateway_image, grpc_bind

    @asynccontextmanager
    async def run(self, _app: Starlette) -> AsyncIterator[None]:
        server = None
        try:
            await self._start_gateway()
            if self._grpc_bind:
                server = await start_server(
                    self._grpc_bind,
                    verifier=self._verifier,
                    identity=self._identity,
                    handler=self._handler,
                    journal=self._journal,
                    node_uuid=self._node.id,
                )
            yield
        finally:
            if server is not None:
                await server.stop(3)
            await self._tasks.close()
            if self._relay is not None:
                await self._relay.close()
            await self._engine.close()
            await self._journal.close()

    async def _start_gateway(self) -> None:
        if self._relay is None:
            return
        if self._gateway_image is None:
            raise ValueError("An immutable Node Gateway image is required")
        from node_agent.gateway_runtime import ensure_gateway
        from node_agent.network_policy_runtime import recover_network_policy_helpers
        from node_agent.workspace_runtime import recover_workspace_helpers

        await ensure_gateway(
            self._engine,
            node_uuid=self._node.id,
            image=self._gateway_image,
            verify_key=os.environ["BRIAREUS_GATEWAY_VERIFY_KEY"],
            core_verify_key=self._verifier.key.public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            ).decode(),
        )
        await recover_workspace_helpers(self._engine, self._node.id)
        await recover_network_policy_helpers(self._engine, self._node.id)
        await self._wait_gateway()

    async def _wait_gateway(self) -> None:
        if self._relay is None:
            return
        async with asyncio.timeout(30):
            while True:
                try:
                    private_gateway_socket()
                    response = await self._relay.client.get("http://node-gateway/health/live")
                    if response.status_code == 200 and response.json() == {"status": "live"}:
                        return
                except (FileNotFoundError, httpx.HTTPError):
                    pass
                await asyncio.sleep(0.5)
