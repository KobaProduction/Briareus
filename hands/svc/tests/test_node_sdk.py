"""Packaged SDK/private-context fixture; not Rauthy or provider acceptance."""

import asyncio
import base64
import hashlib
import os
import time
import unittest
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

import httpx2 as httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from mcp.types import CallToolResult, JSONRPCRequest, ListToolsResult
from starlette.applications import Starlette

from hand_runtime.provider_ipc import ProviderContext
from node_protocol import Deployment, ModuleRelease, ResourceLimits, WorkspaceMount
from node_protocol.effect import NodeEffectPermit, sign_permit
from node_protocol.module_effects import parse_request, resource_id
from node_protocol.provider_context import InvocationPolicies
from svc_hand.node_server import create_app

ACCOUNT_TOOLS = ("github_accounts", "accounts")


@dataclass(frozen=True)
class SignedRequest:
    body: bytes
    headers: dict[str, str]


@dataclass(frozen=True)
class ChildFacts:
    pid: int
    uid: int
    state: str
    capabilities: int
    no_new_privileges: bool

    @classmethod
    def read(cls, path: Path) -> "ChildFacts | None":
        try:
            fields = dict(
                line.split(":", 1)
                for line in (path / "status").read_text().splitlines()
                if ":" in line
            )
        except (FileNotFoundError, ProcessLookupError):
            return None
        return cls(
            int(fields["Pid"]),
            int(fields["Uid"].split()[0]),
            fields["State"].strip()[0],
            int(fields["CapEff"].strip(), 16),
            fields["NoNewPrivs"].strip() == "1",
        )


def children() -> tuple[ChildFacts, ...]:
    result: list[ChildFacts] = []
    for path in Path("/proc").iterdir():
        if path.name.isdigit():
            facts = ChildFacts.read(path)
            if facts is not None and facts.uid == 1000:
                result.append(facts)
    return tuple(result)


def require_packaged_sandbox() -> None:
    assert os.geteuid() == 0
    assert os.statvfs("/").f_flag & os.ST_RDONLY
    assert {path.name for path in Path("/sys/class/net").iterdir()} == {"lo"}
    mapping = Path("/proc/self/uid_map").read_text().splitlines()[0].split()
    assert int(mapping[1]) != 0
    assert not Path("/var/run/docker.sock").exists()


class PackagedNodeSDKTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await asyncio.to_thread(require_packaged_sandbox)
        self.key = Ed25519PrivateKey.generate()
        self.actor, self.session = uuid4(), uuid4()
        self.spec = Deployment(
            id=uuid4(),
            node_uuid=uuid4(),
            project_uuid=uuid4(),
            release=ModuleRelease(
                module="svc",
                image="registry.example/svc@sha256:" + "a" * 64,
                lifecycle="sessionful",
            ),
            limits=ResourceLimits(memory_bytes=512 * 1024**2, cpu_millis=500, pids=96),
            workspace=WorkspaceMount(id=uuid4()),
            effect_verify_key=self.key.public_key()
            .public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
            .decode(),
        )
        self.bearer = "Bearer fixture-not-rauthy"
        self.boundary = create_app(self.spec)

    @asynccontextmanager
    async def runtime(self) -> AsyncIterator[None]:
        application = self.boundary.app
        assert isinstance(application, Starlette)
        async with (
            application.router.lifespan_context(application),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(self.boundary),
                base_url="http://" + self.spec.container_name + ".svc",
            ) as client,
        ):
            self.client = client
            await self.wait_ready()
            yield

    async def wait_ready(self) -> None:
        async with asyncio.timeout(125):
            for _ in range(1250):
                if (await self.client.get("/health/ready")).status_code == 200:
                    return
                await asyncio.sleep(0.1)
        self.fail("Prepared SDK did not become ready")

    def request(
        self,
        method: Literal["tools/list", "tools/call"],
        tool: str | None = None,
        *,
        context: bool = True,
        actor_uuid: UUID | None = None,
        project_uuid: UUID | None = None,
        workspace_uuid: UUID | None = None,
        expires_at: int | None = None,
    ) -> SignedRequest:
        frame = JSONRPCRequest(
            jsonrpc="2.0",
            id=1,
            method=method,
            params={"name": tool, "arguments": {}} if tool is not None else None,
        )
        body = frame.model_dump_json(by_alias=True, exclude_none=True).encode()
        parsed, now = parse_request("svc", body), int(time.time())
        raw = (
            ProviderContext(accounts=(), policies=InvocationPolicies())
            .model_dump_json(exclude_unset=True)
            .encode()
        )
        workspace = self.spec.workspace
        assert workspace is not None
        permit = NodeEffectPermit(
            module="svc",
            node_uuid=self.spec.node_uuid,
            placement_uuid=self.spec.id,
            project_uuid=project_uuid if project_uuid is not None else self.spec.project_uuid,
            workspace_uuid=workspace_uuid if workspace_uuid is not None else workspace.id,
            actor_uuid=actor_uuid if actor_uuid is not None else self.actor,
            agent_session_uuid=self.session,
            request_uuid=uuid4(),
            grant_revision=1,
            fingerprint=self.spec.fingerprint,
            body_digest=hashlib.sha256(body).hexdigest(),
            bearer_digest=hashlib.sha256(self.bearer.encode()).hexdigest(),
            arguments_digest=parsed.arguments_digest,
            method=method,
            tool=parsed.tool,
            resource_id=resource_id(
                "svc", self.spec.node_uuid, self.spec.project_uuid, workspace.id
            ),
            issued_at=now,
            expires_at=expires_at if expires_at is not None else now + 5,
            context_digest=hashlib.sha256(raw).hexdigest() if context else "",
        )
        headers = {
            "content-type": "application/json",
            "authorization": self.bearer,
            "accept": "application/json, text/event-stream",
            "mcp-protocol-version": "2025-11-25",
            "x-briareus-node-permit": sign_permit(permit, self.key),
        }
        if context:
            headers["x-briareus-invocation-context"] = base64.b64encode(raw).decode()
        return SignedRequest(body, headers)

    async def send(self, request: SignedRequest) -> httpx.Response:
        return await self.client.post("/mcp", content=request.body, headers=request.headers)

    async def call(self, tool: str, *, actor_uuid: UUID | None = None) -> CallToolResult:
        response = await self.send(self.request("tools/call", tool, actor_uuid=actor_uuid))
        self.assertEqual(response.status_code, 200, response.text)
        return CallToolResult.model_validate(response.json()["result"])

    async def child(self) -> ChildFacts:
        values = await asyncio.to_thread(children)
        self.assertTrue(values)
        self.assertTrue(
            all(child.capabilities == 0 and child.no_new_privileges for child in values)
        )
        return values[0]

    async def check_catalogue_and_signed_private_project_context(self) -> None:
        listed = await self.send(self.request("tools/list", context=False))
        self.assertEqual(listed.status_code, 200, listed.text)
        catalogue = ListToolsResult.model_validate(listed.json()["result"])
        self.assertEqual(len(catalogue.tools), 145)
        self.assertTrue(set(ACCOUNT_TOOLS).issubset({tool.name for tool in catalogue.tools}))
        self.assertTrue(
            all(
                "x-briareus-invocation-context" not in tool.input_schema.get("properties", {})
                for tool in catalogue.tools
            )
        )
        await self.child()
        for name in ACCOUNT_TOOLS:
            result = await self.call(name)
            self.assertFalse(result.is_error)
            payload = result.structured_content
            assert payload is not None
            self.assertEqual(payload.get("accounts", payload.get("sources")), [])
            self.assertEqual(payload["count"], 0)
            self.assertEqual(
                (await self.client.get("/health/ready")).status_code,
                200,
                "Same-identity calls must not trigger a full child warmup",
            )
            encoded = result.model_dump_json(by_alias=True)
            for private in ("credential", "policies", "context_digest"):
                self.assertNotIn(private, encoded)

    async def check_expiry_pauses_and_fresh_permit_resumes_same_child(self) -> None:
        self.assertFalse((await self.call(ACCOUNT_TOOLS[0])).is_error)
        child = await self.child()
        await asyncio.sleep(5.2)
        paused = await asyncio.to_thread(ChildFacts.read, Path("/proc") / str(child.pid))
        assert paused is not None
        self.assertEqual(paused.state, "T")
        self.assertFalse((await self.call(ACCOUNT_TOOLS[0])).is_error)
        self.assertEqual((await self.child()).pid, child.pid)

    async def check_actor_change_replaces_child_without_replaying_call(self) -> None:
        self.assertFalse((await self.call(ACCOUNT_TOOLS[0])).is_error)
        child = await self.child()
        new_actor = uuid4()
        self.assertTrue((await self.call(ACCOUNT_TOOLS[0], actor_uuid=new_actor)).is_error)
        await self.wait_ready()
        self.assertIsNone(await asyncio.to_thread(ChildFacts.read, Path("/proc") / str(child.pid)))
        self.assertFalse((await self.call(ACCOUNT_TOOLS[0], actor_uuid=new_actor)).is_error)

    async def check_replay_scope_expiry_and_private_context_fail_closed(self) -> None:
        replay = self.request("tools/list", context=False)
        self.assertEqual((await self.send(replay)).status_code, 200)
        self.assertEqual((await self.send(replay)).status_code, 409)
        for invalid in (
            self.request("tools/list", project_uuid=uuid4()),
            self.request("tools/list", workspace_uuid=uuid4()),
            self.request("tools/list", expires_at=int(time.time()) - 1),
        ):
            denied = await self.send(invalid)
            self.assertEqual(denied.status_code, 403, denied.text)
        marker = "private-context-must-not-reflect"
        for mode in ("tamper", "missing", "unbound"):
            request = self.request("tools/list", context=mode != "unbound")
            if mode == "missing":
                del request.headers["x-briareus-invocation-context"]
            else:
                request.headers["x-briareus-invocation-context"] = base64.b64encode(
                    b'{"accounts":[],"marker":"private-context-must-not-reflect"}'
                ).decode()
            denied = await self.send(request)
            self.assertEqual(denied.status_code, 403, denied.text)
            self.assertNotIn(marker, denied.text)
        no_context = await self.send(self.request("tools/call", ACCOUNT_TOOLS[0], context=False))
        self.assertEqual(no_context.status_code, 200, no_context.text)
        self.assertTrue(CallToolResult.model_validate(no_context.json()["result"]).is_error)

    async def test_catalogue_and_signed_private_project_context(self) -> None:
        async with self.runtime():
            await self.check_catalogue_and_signed_private_project_context()

    async def test_expiry_pauses_and_fresh_permit_resumes_same_child(self) -> None:
        async with self.runtime():
            await self.check_expiry_pauses_and_fresh_permit_resumes_same_child()

    async def test_actor_change_replaces_child_without_replaying_call(self) -> None:
        async with self.runtime():
            await self.check_actor_change_replaces_child_without_replaying_call()

    async def test_replay_scope_expiry_and_private_context_fail_closed(self) -> None:
        async with self.runtime():
            await self.check_replay_scope_expiry_and_private_context_fail_closed()
