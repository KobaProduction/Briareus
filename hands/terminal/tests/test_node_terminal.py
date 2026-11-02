"""Native offline SDK dispatch; fixture signatures are not Core acceptance."""

import asyncio
import hashlib
import json
import time
import unittest
from collections.abc import Callable
from typing import Literal
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import httpx2 as httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from mcp.types import CallToolResult, ListToolsResult
from pydantic import BaseModel, JsonValue, TypeAdapter
from starlette.applications import Starlette
from terminal_hand.node_server import create_app
from terminal_hand.worker_server import TerminalSupervisor

from hand_runtime.process_lease import ProcessLease
from node_protocol import Deployment, ModuleRelease, ResourceLimits, WorkspaceMount
from node_protocol.effect import HumanEffectPermit, NodeEffectPermit, sign_permit
from node_protocol.terminal import TOOLS, parse_request, workspace_resource
from runtime_peer.terminal_receipts import JobExecution, JobStatus


class RpcReply[Result](BaseModel):
    result: Result


class NodeTerminalTests(unittest.IsolatedAsyncioTestCase):
    async def test_node_watchdog_prepares_child_again_after_interruption(self) -> None:
        supervisor = TerminalSupervisor.__new__(TerminalSupervisor)
        supervisor.process_lease = ProcessLease(1000)
        supervisor.last_interaction = time.monotonic()
        supervisor.child = None
        supervisor.prewarm = True
        with (
            patch.object(
                supervisor.process_lease,
                "pause_expired",
                new_callable=AsyncMock,
            ) as pause,
            patch.object(
                supervisor,
                "warmup",
                new_callable=AsyncMock,
                side_effect=asyncio.CancelledError,
            ) as warmup,
            patch.dict("os.environ", {"BRIAREUS_RUNTIME_POLICY": "{}"}),
            self.assertRaises(asyncio.CancelledError),
        ):
            try:
                await supervisor.watchdog()
            finally:
                pause.assert_awaited_once()
                warmup.assert_awaited_once()

    async def test_existing_tools_offline_command_and_wrong_authority(self) -> None:
        key = Ed25519PrivateKey.generate()
        workspace = WorkspaceMount(id=uuid4())
        spec = Deployment(
            id=uuid4(),
            node_uuid=uuid4(),
            project_uuid=uuid4(),
            release=ModuleRelease(
                module="terminal",
                image="registry.example/terminal@sha256:" + "a" * 64,
                lifecycle="sessionful",
            ),
            limits=ResourceLimits(memory_bytes=256 * 1024**2, cpu_millis=200, pids=64),
            workspace=workspace,
            effect_verify_key=key.public_key()
            .public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            .decode(),
        )
        app = create_app(spec)
        application = app.app
        assert isinstance(application, Starlette)
        actor, session = uuid4(), uuid4()
        bearer = "Bearer native-fixture-not-provider-identity"
        async with (
            application.router.lifespan_context(application),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app),
                base_url="http://" + spec.container_name + ".terminal",
            ) as client,
        ):

            async def call(
                method: Literal["tools/list", "tools/call"],
                tool: str | None = None,
                arguments: dict[str, JsonValue] | None = None,
                alter: Callable[[NodeEffectPermit], NodeEffectPermit] | None = None,
                *,
                human: bool = False,
                request_id: UUID | None = None,
            ) -> httpx.Response:
                frame: dict[str, JsonValue] = {"jsonrpc": "2.0", "id": 1, "method": method}
                if tool:
                    frame["params"] = {"name": tool, "arguments": arguments or {}}
                body = json.dumps(frame).encode()
                parsed, now = parse_request(body), int(time.time())
                permit = NodeEffectPermit(
                    module="terminal",
                    node_uuid=spec.node_uuid,
                    placement_uuid=spec.id,
                    project_uuid=spec.project_uuid,
                    workspace_uuid=workspace.id,
                    actor_uuid=actor,
                    agent_session_uuid=session,
                    request_uuid=request_id or uuid4(),
                    grant_revision=1,
                    fingerprint=spec.fingerprint,
                    body_digest=hashlib.sha256(body).hexdigest(),
                    bearer_digest=hashlib.sha256(bearer.encode()).hexdigest(),
                    arguments_digest=parsed.arguments_digest,
                    method=method,
                    tool=parsed.tool,
                    resource_id=workspace_resource(
                        spec.node_uuid,
                        spec.project_uuid,
                        workspace.id,
                    ),
                    issued_at=now,
                    expires_at=now + 5,
                )
                if alter is not None:
                    permit = alter(permit)
                return await client.post(
                    "/mcp",
                    content=body,
                    headers={
                        "content-type": "application/json",
                        "authorization": bearer,
                        "accept": "application/json, text/event-stream",
                        "mcp-protocol-version": "2025-11-25",
                        "x-briareus-node-permit": sign_permit(
                            HumanEffectPermit.model_validate(
                                {
                                    **permit.model_dump(
                                        exclude={"agent_session_uuid", "grant_revision"}
                                    ),
                                    "human": True,
                                    "resource_revision": 1,
                                }
                            )
                            if human
                            else permit,
                            key,
                        ),
                    },
                )

            async def result(
                tool: str,
                arguments: dict[str, JsonValue],
                *,
                human: bool = False,
            ) -> CallToolResult:
                response = await call("tools/call", tool, arguments, human=human)
                self.assertEqual(response.status_code, 200, response.text)
                reply = RpcReply[CallToolResult].model_validate_json(response.content).result
                self.assertFalse(reply.is_error, response.text)
                return reply

            response = await call("tools/list")
            self.assertEqual(response.status_code, 200, response.text)
            tools = RpcReply[ListToolsResult].model_validate_json(response.content).result.tools
            self.assertEqual({tool.name for tool in tools}, TOOLS)
            catalogue = {tool.name: tool for tool in tools}
            execution = catalogue["terminal_exec"].input_schema["properties"]["timeout_seconds"]
            self.assertIsNone(execution["default"])
            self.assertNotIn("maximum", execution)
            timeout = catalogue["job_wait"].input_schema["properties"]["timeout_seconds"]
            self.assertEqual(timeout["default"], 3)
            self.assertEqual(timeout["maximum"], 3)
            await result("workspace_create", {"workspace_id": "node-acceptance"})
            executed = await result(
                "terminal_exec",
                {
                    "workspace_id": "node-acceptance",
                    "command": (
                        "id -u; ls /sys/class/net; "
                        "if test -r /proc/1/environ; then exit 91; fi; printf offline-ok"
                    ),
                },
            )
            receipt = TypeAdapter(JobExecution).validate_python(executed.structured_content)
            self.assertEqual(receipt.exit_code, 0)
            self.assertEqual(receipt.stdout, "1000\nlo\noffline-ok")
            started = await result(
                "job_start",
                {
                    "workspace_id": "node-acceptance",
                    "command": "sleep 60",
                    "label": "lease-expiry-fixture",
                },
            )
            job = TypeAdapter(JobStatus).validate_python(started.structured_content)
            supervisor = application.state.terminal_supervisor
            assert isinstance(supervisor, TerminalSupervisor)
            self.assertIsNotNone(supervisor.lease)
            assert supervisor.child is not None and supervisor.process_lease is not None
            manager_pid = supervisor.child.pid
            await asyncio.sleep(6)
            self.assertEqual(supervisor.process_lease.status, "paused")
            self.assertEqual(supervisor.child.pid, manager_pid)
            self.assertTrue(
                all(state in {"T", "t"} for state in supervisor.process_lease._processes().values())
            )
            status = await result("job_status", {"job_id": job.job_id})
            self.assertEqual(
                TypeAdapter(JobStatus).validate_python(status.structured_content).state, "running"
            )
            self.assertEqual(supervisor.process_lease.status, "active")
            self.assertEqual(supervisor.child.pid, manager_pid)
            other = await call(
                "tools/call",
                "workspace_list",
                {},
                alter=lambda p: p.model_copy(update={"actor_uuid": uuid4()}),
            )
            self.assertEqual(other.status_code, 200, other.text)
            self.assertTrue(
                RpcReply[CallToolResult].model_validate_json(other.content).result.is_error
            )
            await supervisor.warmup()
            assert supervisor.child is not None
            self.assertNotEqual(supervisor.child.pid, manager_pid)
            status = await result("job_status", {"job_id": job.job_id})
            self.assertEqual(
                TypeAdapter(JobStatus).validate_python(status.structured_content).state,
                "interrupted",
            )
            changes: tuple[Callable[[NodeEffectPermit], NodeEffectPermit], ...] = (
                lambda p: p.model_copy(update={"workspace_uuid": uuid4()}),
                lambda p: p.model_copy(update={"module": "files"}),
                lambda p: p.model_copy(update={"expires_at": int(time.time()) - 1}),
            )
            for alter in changes:
                denied = await call("tools/list", alter=alter)
                self.assertEqual(denied.status_code, 403, denied.text)

            # Switching from the agent to the human prepares a distinct persisted job namespace.
            await call("tools/call", "terminal_status", {}, human=True)
            await supervisor.warmup()
            await result("terminal_status", {}, human=True)
            await result("workspace_create", {"workspace_id": "human-owned"}, human=True)
            operation = uuid4()
            parameters: dict[str, JsonValue] = {
                "workspace_id": "human-owned",
                "command": "printf human-project-ok",
            }
            first = await call(
                "tools/call", "job_start", parameters, human=True, request_id=operation
            )
            first_reply = RpcReply[CallToolResult].model_validate_json(first.content).result
            self.assertFalse(first_reply.is_error, first.text)
            human_job = TypeAdapter(JobStatus).validate_python(first_reply.structured_content)
            self.assertEqual(human_job.job_id, operation.hex)
            duplicate = await call(
                "tools/call", "job_start", parameters, human=True, request_id=operation
            )
            self.assertEqual(duplicate.status_code, 409, duplicate.text)
            await asyncio.sleep(6)
            duplicate = await call(
                "tools/call", "job_start", parameters, human=True, request_id=operation
            )
            duplicate_reply = RpcReply[CallToolResult].model_validate_json(duplicate.content).result
            self.assertFalse(duplicate_reply.is_error, duplicate.text)
            self.assertEqual(
                TypeAdapter(JobStatus).validate_python(duplicate_reply.structured_content).job_id,
                human_job.job_id,
            )
            read = await result(
                "job_read",
                {
                    "job_id": human_job.job_id,
                    "wait_seconds": 1,
                },
                human=True,
            )
            self.assertIn("human-project-ok", str(read.structured_content))
            foreign = await call("tools/call", "job_read", {"job_id": job.job_id}, human=True)
            self.assertTrue(
                RpcReply[CallToolResult].model_validate_json(foreign.content).result.is_error
            )
