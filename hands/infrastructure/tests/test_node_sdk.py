"""Packaged SDK/private-context fixture; not Rauthy or provider acceptance."""
import asyncio
import base64
import hashlib
import json
import os
import time
import unittest
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import uuid4

import httpx2 as httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from mcp.types import CallToolResult, ListToolsResult
from pydantic import BaseModel, JsonValue
from starlette.applications import Starlette

from common.account_contracts import SourceInventoryView
from infrastructure_hand.node_server import create_app
from node_protocol import Deployment, ModuleRelease, ResourceLimits, WorkspaceMount
from node_protocol.effect import NodeEffectPermit, sign_permit
from node_protocol.module_effects import parse_request, resource_id
from node_protocol.provider_context import InvocationContext, InvocationPolicies

MODULE: Literal["infrastructure"] = "infrastructure"
ACCOUNT_TOOLS = ["observability_sources"]


@dataclass(frozen=True)
class InvocationFrame:
    body: bytes
    headers: dict[str, str]


@dataclass(frozen=True)
class ProcessSnapshot:
    pid: int
    uid: int
    capabilities: int
    no_new_privileges: bool
    state: str

    @classmethod
    def read(cls, folder: Path) -> "ProcessSnapshot":
        fields = dict(
            line.split(":", 1)
            for line in (folder / "status").read_text().splitlines()
            if ":" in line
        )
        return cls(
            int(folder.name), int(fields["Uid"].split()[0]), int(fields["CapEff"].strip(), 16),
            fields["NoNewPrivs"].strip() == "1", fields["State"].strip()[0],
        )


class RpcReply[Result](BaseModel):
    result: Result

class PackagedNodeSDKTests(unittest.IsolatedAsyncioTestCase):
    def require_isolation(self) -> None:
        self.assertEqual(os.geteuid(), 0)
        self.assertTrue(os.statvfs("/").f_flag & os.ST_RDONLY)
        self.assertEqual({p.name for p in Path("/sys/class/net").iterdir()}, {"lo"})
        mapping = Path("/proc/self/uid_map").read_text().splitlines()[0].split()
        self.assertNotEqual(int(mapping[1]), 0)

    async def asyncSetUp(self) -> None:
        await asyncio.to_thread(self.require_isolation)
        self.key = Ed25519PrivateKey.generate()
        self.actor, self.session, self.storage = uuid4(), uuid4(), uuid4()
        self.spec = Deployment(
            id=uuid4(), node_uuid=uuid4(), project_uuid=uuid4(),
            release=ModuleRelease(
                module=MODULE, image="registry.example/infrastructure@sha256:" + "a" * 64,
                lifecycle="sessionful",
            ),
            limits=ResourceLimits(memory_bytes=512*1024**2, cpu_millis=500, pids=96),
            workspace=WorkspaceMount(id=self.storage),
            effect_verify_key=self.key.public_key().public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
            ).decode(),
        )
        self.bearer = "Bearer fixture-not-rauthy"
        self.private_context = InvocationContext(
            accounts=(), policies=InvocationPolicies(),
        ).model_dump_json(exclude_none=True).encode()
        self.app = create_app(self.spec)
        assert isinstance(self.app.app, Starlette)
        self.application = self.app.app

    async def ready(self) -> None:
        async with asyncio.timeout(125):
            while True:
                response = await self.client.get("/health/ready")
                if response.status_code == 200:
                    return
                await asyncio.sleep(0.1)

    def request(
        self, method: Literal["tools/list", "tools/call"], tool: str | None = None,
        *, context: bool = True,
        alter: Callable[[NodeEffectPermit], NodeEffectPermit] | None = None,
    ) -> InvocationFrame:
        frame: dict[str, JsonValue] = {"jsonrpc": "2.0", "id": 1, "method": method}
        if tool is not None:
            frame["params"] = {"name": tool, "arguments": {}}
        body = json.dumps(frame, separators=(",", ":")).encode()
        parsed, now = parse_request(MODULE, body), int(time.time())
        permit = NodeEffectPermit(
            module=MODULE, node_uuid=self.spec.node_uuid, placement_uuid=self.spec.id,
            project_uuid=self.spec.project_uuid, workspace_uuid=self.storage,
            actor_uuid=self.actor, agent_session_uuid=self.session, request_uuid=uuid4(),
            grant_revision=1, fingerprint=self.spec.fingerprint,
            body_digest=hashlib.sha256(body).hexdigest(),
            bearer_digest=hashlib.sha256(self.bearer.encode()).hexdigest(),
            arguments_digest=parsed.arguments_digest, method=method, tool=parsed.tool,
            resource_id=resource_id(
                MODULE, self.spec.node_uuid, self.spec.project_uuid, self.storage,
            ),
            issued_at=now, expires_at=now+5,
            context_digest=hashlib.sha256(self.private_context).hexdigest() if context else "",
        )
        if alter is not None:
            permit = alter(permit)
        headers = {
            "content-type": "application/json", "authorization": self.bearer,
            "accept": "application/json, text/event-stream", "mcp-protocol-version": "2025-11-25",
            "x-briareus-node-permit": sign_permit(permit, self.key),
        }
        if context:
            headers["x-briareus-invocation-context"] = (
                base64.b64encode(self.private_context).decode()
            )
        return InvocationFrame(body, headers)

    async def send(self, frame: InvocationFrame) -> httpx.Response:
        return await self.client.post("/mcp", content=frame.body, headers=frame.headers)

    async def call(self, frame: InvocationFrame) -> CallToolResult:
        response = await self.send(frame)
        self.assertEqual(response.status_code, 200, response.text)
        return RpcReply[CallToolResult].model_validate_json(response.content).result

    def children(self) -> tuple[ProcessSnapshot, ...]:
        children = []
        for folder in Path("/proc").iterdir():
            if not folder.name.isdigit():
                continue
            try:
                snapshot = ProcessSnapshot.read(folder)
            except (FileNotFoundError, ProcessLookupError):
                continue
            if snapshot.uid == 1000:
                children.append(snapshot)
        return tuple(children)

    async def check_catalogue(self) -> None:
        response = await self.send(self.request("tools/list", context=False))
        self.assertEqual(response.status_code, 200, response.text)
        catalogue = RpcReply[ListToolsResult].model_validate_json(response.content).result.tools
        self.assertEqual(len(catalogue), 21)
        names = {tool.name for tool in catalogue}
        self.assertTrue(set(ACCOUNT_TOOLS).issubset(names))
        self.assertTrue({
            "infrastructure_operation_start", "infrastructure_operation_poll",
            "infrastructure_operation_cancel",
        }.issubset(names))
        for tool in catalogue:
            self.assertIsInstance(tool.input_schema, dict)
            self.assertNotIn(
                "x-briareus-invocation-context", tool.input_schema.get("properties", {}),
            )

    async def check_sources(self) -> None:
        for name in ACCOUNT_TOOLS:
            response = await self.send(self.request("tools/call", name))
            self.assertEqual(response.status_code, 200, response.text)
            result = RpcReply[CallToolResult].model_validate_json(response.content).result
            self.assertFalse(result.is_error, response.text)
            sources = SourceInventoryView.model_validate(result.structured_content)
            self.assertEqual(sources.sources, [])
            self.assertEqual(sources.count, 0)
            self.assertEqual((await self.client.get("/health/ready")).status_code, 200)
            for private in ("credential", "policies", "context_digest"):
                self.assertNotIn(private, response.text)

    async def check_expiry_and_rebinding(self, child: ProcessSnapshot) -> None:
        await asyncio.sleep(5.2)
        status_path = Path("/proc") / str(child.pid)
        self.assertEqual(ProcessSnapshot.read(status_path).state, "T")
        resumed = await self.call(self.request("tools/call", ACCOUNT_TOOLS[0]))
        self.assertFalse(resumed.is_error)
        new_actor = uuid4()
        def change(permit: NodeEffectPermit) -> NodeEffectPermit:
            return permit.model_copy(update={"actor_uuid": new_actor})
        changed = await self.call(self.request("tools/call", ACCOUNT_TOOLS[0], alter=change))
        self.assertTrue(changed.is_error)
        await self.ready()
        self.assertFalse(status_path.exists())
        fresh = await self.call(self.request("tools/call", ACCOUNT_TOOLS[0], alter=change))
        self.assertFalse(fresh.is_error)
        await self.ready()

    async def check_replay_and_bindings(self) -> None:
        replay = self.request("tools/list", context=False)
        self.assertEqual((await self.send(replay)).status_code, 200)
        self.assertEqual((await self.send(replay)).status_code, 409)
        changes: tuple[Callable[[NodeEffectPermit], NodeEffectPermit], ...] = (
            lambda p: p.model_copy(update={"project_uuid": uuid4()}),
            lambda p: p.model_copy(update={"workspace_uuid": uuid4()}),
            lambda p: p.model_copy(update={"expires_at": int(time.time())-1}),
        )
        for change in changes:
            denied = await self.send(self.request("tools/list", alter=change))
            self.assertEqual(denied.status_code, 403, denied.text)

    async def check_context_integrity(self) -> None:
        marker = "private-context-must-not-reflect"
        for mode in ("tamper", "missing", "unbound"):
            frame = self.request("tools/list", context=mode != "unbound")
            if mode == "missing":
                del frame.headers["x-briareus-invocation-context"]
            else:
                frame.headers["x-briareus-invocation-context"] = base64.b64encode(
                    json.dumps({"accounts": [], "marker": marker}).encode(),
                ).decode()
            denied = await self.send(frame)
            self.assertEqual(denied.status_code, 403, denied.text)
            self.assertNotIn(marker, denied.text)
        await self.ready()
        no_context = await self.call(self.request("tools/call", ACCOUNT_TOOLS[0], context=False))
        self.assertTrue(no_context.is_error)

    async def test_catalogue_and_signed_private_project_context(self) -> None:
        async with self.application.router.lifespan_context(self.application), httpx.AsyncClient(
            transport=httpx.ASGITransport(self.app),
            base_url="http://" + self.spec.container_name + "." + MODULE,
        ) as client:
            self.client = client
            await self.check_catalogue()
            children = self.children()
            self.assertTrue(children)
            self.assertTrue(all(
                child.capabilities == 0 and child.no_new_privileges for child in children
            ))
            self.assertFalse(await asyncio.to_thread(Path("/var/run/docker.sock").exists))
            await self.check_sources()
            await self.check_expiry_and_rebinding(children[0])
            await self.check_replay_and_bindings()
            await self.check_context_integrity()
