"""Actual FastMCP dispatch with signed per-request authority and private fixture files."""

import asyncio
import base64
import hashlib
import json
import tempfile
import time
import unittest
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

import httpx2 as httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from files_hand.node_dispatch import READ_TOOLS, WRITE_TOOLS
from files_hand.node_server import create_app
from mcp.types import CallToolResult
from pydantic import JsonValue
from starlette.applications import Starlette

from node_protocol import Deployment, ModuleRelease, ResourceLimits, WorkspaceMount
from node_protocol.effect import NodeEffectPermit, sign_permit
from node_protocol.files import parse_request, workspace_resource


class NodeFilesTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        Path(self.folder.name, "fixture.txt").write_text("private fixture content")
        Path(self.folder.name, "fixture.txt").chmod(0o600)
        self.key = Ed25519PrivateKey.generate()
        self.spec = Deployment(
            id=uuid4(),
            node_uuid=uuid4(),
            project_uuid=uuid4(),
            release=ModuleRelease(
                module="files",
                image="registry.example/files@sha256:" + "a" * 64,
                lifecycle="sessionful",
            ),
            limits=ResourceLimits(memory_bytes=128 * 1024**2, cpu_millis=100, pids=32),
            workspace=WorkspaceMount(id=uuid4()),
            effect_verify_key=self.key.public_key()
            .public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
            .decode(),
        )
        self.bearer = "Bearer provider-fixture-for-bound-signature"

    async def asyncSetUp(self) -> None:
        self.app = create_app(self.spec, self.folder.name)
        ready, self.stop = asyncio.Event(), asyncio.Event()

        async def lifespan() -> None:
            application = self.app.app
            assert isinstance(application, Starlette)
            async with application.router.lifespan_context(application):
                ready.set()
                await self.stop.wait()

        self.lifespan_task = asyncio.create_task(lifespan())
        await ready.wait()
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(self.app),
            base_url=f"http://{self.spec.container_name}:8000",
        )

    async def asyncTearDown(self) -> None:
        await self.client.aclose()
        self.stop.set()
        await self.lifespan_task
        self.folder.cleanup()

    def authority(
        self, body: bytes, *, workspace_uuid: UUID | None = None, expires_at: int | None = None
    ) -> str:
        frame = parse_request(body)
        workspace = self.spec.workspace
        assert workspace is not None
        method: Literal["tools/list", "tools/call"]
        if frame.method == "tools/list":
            method = "tools/list"
        elif frame.method == "tools/call":
            method = "tools/call"
        else:
            raise ValueError("Unexpected Files fixture method")
        now = int(time.time())
        permit = NodeEffectPermit(
            node_uuid=self.spec.node_uuid,
            placement_uuid=self.spec.id,
            project_uuid=self.spec.project_uuid,
            workspace_uuid=workspace_uuid if workspace_uuid is not None else workspace.id,
            actor_uuid=uuid4(),
            agent_session_uuid=uuid4(),
            request_uuid=uuid4(),
            grant_revision=1,
            fingerprint=self.spec.fingerprint,
            body_digest=hashlib.sha256(body).hexdigest(),
            bearer_digest=hashlib.sha256(self.bearer.encode()).hexdigest(),
            arguments_digest=frame.arguments_digest,
            method=method,
            tool=frame.tool,
            resource_id=workspace_resource(
                self.spec.node_uuid, self.spec.project_uuid, workspace.id
            ),
            issued_at=now,
            expires_at=expires_at if expires_at is not None else now + 5,
        )
        return sign_permit(permit, self.key)

    async def post(self, body: bytes, permit: str | None = None) -> httpx.Response:
        return await self.client.post(
            "/mcp",
            content=body,
            headers={
                "content-type": "application/json",
                "accept": "application/json, text/event-stream",
                "authorization": self.bearer,
                "x-briareus-node-permit": permit or self.authority(body),
                "mcp-protocol-version": "2025-11-25",
            },
        )

    async def test_original_sdk_catalogue_and_confined_read_then_replay_denied(self) -> None:
        listing = b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
        response = await self.post(listing)
        self.assertEqual(response.status_code, 200, response.text)
        tools = {item["name"]: item for item in response.json()["result"]["tools"]}
        self.assertEqual(set(tools), READ_TOOLS | WRITE_TOOLS)
        self.assertEqual(tools["file_ingest"]["_meta"]["openai/fileParams"], ["file"])
        body = (
            b'{"jsonrpc":"2.0","id":2,"method":"tools/call",'
            b'"params":{"name":"file_read","arguments":{"path":"fixture.txt"}}}'
        )
        permit = self.authority(body)
        response = await self.post(body, permit)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["result"].get("isError"), response.text)
        self.assertEqual(
            base64.b64decode(response.json()["result"]["structuredContent"]["data_base64"]),
            b"private fixture content",
        )
        self.assertEqual((await self.post(body, permit)).status_code, 409)
        self.assertEqual(
            (await self.post(body.replace(b"fixture.txt", b"other.txt"), permit)).status_code, 403
        )

    async def test_wrong_workspace_expired_key_and_traversal_never_release_data(self) -> None:
        body = (
            b'{"jsonrpc":"2.0","id":3,"method":"tools/call",'
            b'"params":{"name":"file_read","arguments":{"path":"../fixture.txt"}}}'
        )
        response = await self.post(body)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["result"]["isError"])
        for permit in (
            self.authority(body, workspace_uuid=uuid4()),
            self.authority(body, expires_at=int(time.time()) - 1),
        ):
            self.assertEqual((await self.post(body, permit)).status_code, 403)
        original = self.key
        self.key = Ed25519PrivateKey.generate()
        self.assertEqual((await self.post(body, self.authority(body))).status_code, 403)
        self.key = original

    async def test_signed_sdk_write_copy_move_chunk_read_and_delete(self) -> None:
        async def call(name: str, arguments: dict[str, JsonValue]) -> CallToolResult:
            body = json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 7,
                    "method": "tools/call",
                    "params": {"name": name, "arguments": arguments},
                },
                separators=(",", ":"),
            ).encode()
            response = await self.post(body)
            self.assertEqual(response.status_code, 200, response.text)
            result = CallToolResult.model_validate(response.json()["result"])
            self.assertFalse(result.is_error, response.text)
            return result

        await call("file_mkdir", {"path": "created"})
        await call("file_write_text", {"path": "created/source.txt", "content": "source"})
        await call(
            "file_write",
            {
                "path": "created/source.txt",
                "offset": 6,
                "data_base64": base64.b64encode(b" appended").decode(),
            },
        )
        await call("file_copy", {"source": "created", "destination": "copied"})
        await call("file_move", {"source": "copied/source.txt", "destination": "moved.txt"})
        result = await call("file_read", {"path": "moved.txt"})
        assert result.structured_content is not None
        self.assertEqual(
            base64.b64decode(result.structured_content["data_base64"]), b"source appended"
        )
        await call("file_delete", {"path": "copied", "recursive": True})
        await call("file_delete", {"path": "moved.txt"})
