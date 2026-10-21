"""Native offline SDK dispatch; fixture signatures are not Core acceptance."""
import asyncio
import hashlib
import json
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx2 as httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from node_protocol import Deployment, ModuleRelease, ResourceLimits, WorkspaceMount
from node_protocol.control import canonical
from node_protocol.effect import NodeEffectPermit, sign_permit
from node_protocol.terminal import TOOLS, parse_request, workspace_resource
from terminal_hand.node_server import create_app


class NodeTerminalTests(unittest.IsolatedAsyncioTestCase):
    async def test_node_watchdog_prepares_child_again_after_interruption(self):
        from terminal_hand.worker_server import TerminalSupervisor
        supervisor=TerminalSupervisor.__new__(TerminalSupervisor)
        supervisor.process_lease=SimpleNamespace(pause_expired=AsyncMock())
        supervisor.last_interaction=time.monotonic()
        supervisor.child=None
        supervisor.prewarm=True
        supervisor.warmup=AsyncMock(side_effect=asyncio.CancelledError)
        with patch.dict("os.environ",{"BRIAREUS_RUNTIME_POLICY":"{}"}):
            with self.assertRaises(asyncio.CancelledError):
                await supervisor.watchdog()
        supervisor.process_lease.pause_expired.assert_awaited_once()
        supervisor.warmup.assert_awaited_once()

    async def test_existing_tools_offline_command_and_wrong_authority(self):
        key = Ed25519PrivateKey.generate()
        spec = Deployment(id=uuid4(), node_uuid=uuid4(), project_uuid=uuid4(),
            release=ModuleRelease(module="terminal", image="registry.example/terminal@sha256:" + "a" * 64,
                lifecycle="sessionful"), limits=ResourceLimits(memory_bytes=256*1024**2, cpu_millis=200, pids=64),
            workspace=WorkspaceMount(id=uuid4()), effect_verify_key=key.public_key().public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode())
        app = create_app(spec)
        actor, session = uuid4(), uuid4()
        bearer = "Bearer native-fixture-not-provider-identity"
        async with app.app.router.lifespan_context(app.app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app),
                base_url="http://" + spec.container_name + ".terminal") as client:
                async def call(method, tool=None, arguments=None, **changes):
                    frame = {"jsonrpc": "2.0", "id": 1, "method": method}
                    if tool:
                        frame["params"] = {"name": tool, "arguments": arguments or {}}
                    body = json.dumps(frame).encode()
                    parsed, now = parse_request(body), int(time.time())
                    values = dict(module="terminal", node_uuid=spec.node_uuid, placement_uuid=spec.id,
                        project_uuid=spec.project_uuid, workspace_uuid=spec.workspace.id, actor_uuid=actor,
                        agent_session_uuid=session, request_uuid=uuid4(), grant_revision=1,
                        fingerprint=spec.fingerprint, body_digest=hashlib.sha256(body).hexdigest(),
                        bearer_digest=hashlib.sha256(bearer.encode()).hexdigest(),
                        arguments_digest=hashlib.sha256(canonical(parsed.arguments)).hexdigest(),
                        method=parsed.method, tool=parsed.tool,
                        resource_id=workspace_resource(spec.node_uuid, spec.project_uuid, spec.workspace.id),
                        issued_at=now, expires_at=now+5)
                    values.update(changes)
                    response = await client.post("/mcp", content=body, headers={"content-type": "application/json",
                        "authorization": bearer, "accept": "application/json, text/event-stream",
                        "mcp-protocol-version": "2025-11-25",
                        "x-briareus-node-permit": sign_permit(NodeEffectPermit(**values), key)})
                    return response
                tools = await call("tools/list")
                self.assertEqual(tools.status_code, 200, tools.text)
                self.assertEqual({tool["name"] for tool in tools.json()["result"]["tools"]}, TOOLS)
                catalogue = {tool["name"]:tool for tool in tools.json()["result"]["tools"]}
                execution = catalogue["terminal_exec"]["inputSchema"]["properties"]["timeout_seconds"]
                self.assertIsNone(execution["default"])
                self.assertNotIn("maximum", execution)
                for name in ("job_wait",):
                    timeout = catalogue[name]["inputSchema"]["properties"]["timeout_seconds"]
                    self.assertEqual(timeout["default"],3)
                    self.assertEqual(timeout["maximum"],3)
                created = await call("tools/call", "workspace_create", {"workspace_id": "node-acceptance"})
                self.assertEqual(created.status_code, 200, created.text)
                self.assertFalse(created.json()["result"].get("isError"), created.text)
                executed = await call("tools/call", "terminal_exec", {"workspace_id": "node-acceptance",
                    "command": "id -u; ls /sys/class/net; if test -r /proc/1/environ; then exit 91; fi; printf offline-ok"})
                self.assertEqual(executed.status_code, 200, executed.text)
                self.assertFalse(executed.json()["result"].get("isError"), executed.text)
                result = executed.json()["result"]["structuredContent"]
                self.assertEqual(result["exit_code"], 0, result)
                self.assertEqual(result["stdout"], "1000\nlo\noffline-ok")
                started = await call("tools/call", "job_start", {"workspace_id": "node-acceptance",
                    "command": "sleep 60", "label": "lease-expiry-fixture"})
                self.assertEqual(started.status_code, 200, started.text)
                self.assertFalse(started.json()["result"].get("isError"), started.text)
                job = started.json()["result"]["structuredContent"]
                supervisor = app.app.state.terminal_supervisor
                self.assertIsNotNone(supervisor.lease)
                manager_pid = supervisor.child.pid
                await asyncio.sleep(6)
                self.assertEqual(supervisor.process_lease.status, "paused")
                self.assertEqual(supervisor.child.pid, manager_pid)
                self.assertTrue(all(state in {"T", "t"} for state in supervisor.process_lease._processes().values()))
                status = await call("tools/call", "job_status", {"job_id": job["job_id"]})
                self.assertEqual(status.status_code, 200, status.text)
                self.assertFalse(status.json()["result"].get("isError"), status.text)
                self.assertEqual(status.json()["result"]["structuredContent"]["state"], "running")
                self.assertEqual(supervisor.process_lease.status, "active")
                self.assertEqual(supervisor.child.pid, manager_pid)
                other = await call("tools/call", "workspace_list", {}, actor_uuid=uuid4())
                self.assertEqual(other.status_code, 200, other.text)
                self.assertTrue(other.json()["result"].get("isError"), other.text)
                await supervisor.warmup()
                self.assertNotEqual(supervisor.child.pid, manager_pid)
                status = await call("tools/call", "job_status", {"job_id": job["job_id"]})
                self.assertEqual(status.status_code, 200, status.text)
                self.assertEqual(status.json()["result"]["structuredContent"]["state"], "interrupted")
                for changes in [{"workspace_uuid": uuid4()}, {"module": "files"},
                    {"expires_at": int(time.time())-1}]:
                    denied = await call("tools/list", **changes)
                    self.assertEqual(denied.status_code, 403, denied.text)
