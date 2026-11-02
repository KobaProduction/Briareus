"""Writer fencing shuts down the controller without restarting persistent Hands."""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from node_agent.control_auth import CoreVerifier
from node_agent.docker_engine import DockerEngine
from node_agent.infrastructure.server_runtime import serve_controller
from node_agent.journal import Journal, JournalUnavailable
from node_agent.server import create_app
from test_reconciliation import fixture


class Server:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.finished = asyncio.Event()
        self._exit = False

    @property
    def should_exit(self) -> bool:
        return self._exit

    @should_exit.setter
    def should_exit(self, value: bool) -> None:
        self._exit = value
        if value:
            self.finished.set()

    async def serve(self) -> None:
        self.started.set()
        await self.finished.wait()


class ServerRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_lease_loss_requests_graceful_server_shutdown(self) -> None:
        server, lost = Server(), asyncio.Event()
        task = asyncio.create_task(serve_controller(server, lost))
        await server.started.wait()
        self.assertFalse(task.done())
        lost.set()
        await asyncio.wait_for(task, 1)
        self.assertTrue(server.should_exit)

    async def test_normal_server_stop_does_not_wait_for_lease_loss(self) -> None:
        server, lost = Server(), asyncio.Event()
        server.finished.set()
        await asyncio.wait_for(serve_controller(server, lost), 1)
        self.assertFalse(server.should_exit)
        self.assertFalse(lost.is_set())

    async def test_cancellation_closes_both_watch_tasks(self) -> None:
        server, lost = Server(), asyncio.Event()
        task = asyncio.create_task(serve_controller(server, lost))
        await server.started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(lost.is_set())


class ReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        node, _ = fixture()
        public = (
            Ed25519PrivateKey.generate()
            .public_key()
            .public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
        )
        # Readiness initializes owner authority without opening an engine connection.
        self.engine = DockerEngine.__new__(DockerEngine)
        self.journal = Journal.__new__(Journal)
        self.journal.lost = asyncio.Event()
        app = create_app(node, self.engine, self.journal, CoreVerifier(public, node.id))
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://node")

    async def asyncTearDown(self) -> None:
        await self.client.aclose()

    async def test_readiness_initializes_authority_and_rejects_lost_lease(self) -> None:
        with patch.object(self.journal, "configuration", AsyncMock(return_value=None)) as read:
            self.assertEqual((await self.client.get("/health/ready")).status_code, 200)
            read.assert_awaited_once()
            self.journal.lost.set()
            self.assertEqual((await self.client.get("/health/ready")).status_code, 503)
            self.assertEqual((await self.client.get("/health/live")).status_code, 200)

    async def test_missing_owner_authority_never_reports_ready(self) -> None:
        with patch.object(self.journal, "configuration", AsyncMock(side_effect=JournalUnavailable)):
            response = await self.client.get("/health/ready")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"code": "NODE_RUNTIME_UNAVAILABLE"})
