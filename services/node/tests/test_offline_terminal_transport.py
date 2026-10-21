"""Offline transport boundaries; real Unix sockets, no live Core or Docker API."""
import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from node_protocol import WorkspaceMount, ResourceLimits, Deployment
from node_protocol.terminal import parse_request, workspace_resource
from node_agent.dataplane import worker_target
from node_agent.docker_engine import EngineFailure, container_config
from node_agent.worker_transport import WorkerTransport
from node_agent.workspace_init import initialize_runtime
from node_agent.workspace_runtime import initializer_config
from test_reconciliation import fixture


class TerminalContractTests(unittest.TestCase):
    def test_offline_supervisor_configuration_and_project_binding(self):
        _, original = fixture()
        key = Ed25519PrivateKey.generate().public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        spec = original.model_copy(update={"release": original.release.model_copy(update={
            "module": "terminal", "lifecycle": "sessionful"}),
            "workspace": WorkspaceMount(id=uuid4()), "effect_verify_key": key,
            "limits": ResourceLimits(memory_bytes=256*1024**2,cpu_millis=200,pids=64)})
        spec = Deployment.model_validate(spec.model_dump())
        with self.assertRaises(ValueError):
            Deployment.model_validate({**spec.model_dump(),"limits":original.limits.model_dump()})
        config = container_config(spec)
        host = config["HostConfig"]
        self.assertEqual(host["NetworkMode"], "none")
        self.assertFalse(host["Privileged"])
        self.assertEqual(host["CapDrop"], ["ALL"])
        self.assertEqual(set(host["CapAdd"]), {"SETUID", "SETGID", "KILL"})
        self.assertEqual(config["User"], "0:0")  # Supervisor only; command contract stays 1000.
        with self.assertRaises(EngineFailure):
            container_config(spec.model_copy(update={"workspace": None}))
        self.assertEqual(spec.release.run_as, "1000:1000")
        self.assertEqual(len(host["Binds"]), 1)
        self.assertEqual(host["Binds"][0],
            f"/var/lib/briareus/nodes/{spec.node_uuid}/gateway/workers/{spec.container_name}:/terminal-link:rw")
        self.assertNotIn("docker.sock", str(config))
        self.assertIn("uid=1000,gid=1000", host["Tmpfs"]["/home/agent"])
        helper = initializer_config(spec, "registry.example/node@sha256:" + "a" * 64)
        self.assertIn("BRIAREUS_RUNTIME_WORKER=" + spec.container_name, helper["Env"])
        self.assertEqual(worker_target(type("Proof", (), {
            "module": "terminal", "container_name": spec.container_name})()),
            "http://" + spec.container_name + ".terminal/mcp")
        self.assertNotEqual(workspace_resource(spec.node_uuid, spec.project_uuid, spec.workspace.id),
            workspace_resource(spec.node_uuid, uuid4(), spec.workspace.id))

    def test_quick_requests_cannot_outlive_authority(self):
        import json
        def request(tool, arguments):
            return json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": tool, "arguments": arguments}}).encode()
        self.assertEqual(parse_request(request("terminal_exec", {"timeout_seconds": 3})).tool, "terminal_exec")
        self.assertEqual(parse_request(request("terminal_exec", {})).tool, "terminal_exec")
        self.assertEqual(parse_request(request("job_wait", {})).tool, "job_wait")
        for tool, arguments in [("terminal_exec", {"timeout_seconds": 60}), ("terminal_exec", {"timeout_seconds": True}),
            ("job_wait", {"timeout_seconds": 60}), ("job_read", {"wait_seconds": 4}), ("file_read", {})]:
            with self.assertRaises(ValueError):
                parse_request(request(tool, arguments))
        self.assertEqual(parse_request(request("job_start", {"command": "sleep 10"})).tool, "job_start")


@unittest.skipUnless(hasattr(asyncio, "start_unix_server"), "Unix sockets required")
class OfflineTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_socket_permissions_and_no_network_fallback(self):
        with tempfile.TemporaryDirectory() as root:
            name = "briareus-" + "a" * 48
            directory = Path(root) / name
            directory.mkdir(mode=0o700)
            path = directory / "mcp.sock"
            async def respond(reader, writer):
                try:
                    await reader.readuntil(b"\r\n\r\n")
                    writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}")
                    await writer.drain()
                finally:
                    writer.close()
                    await writer.wait_closed()
            server = await asyncio.start_unix_server(respond, path=str(path))
            path.chmod(0o600)
            transport = WorkerTransport(root)
            async def forbidden_network(request):
                raise AssertionError("Offline worker must never fall back to TCP")
            await transport.network.aclose()
            transport.network = httpx.MockTransport(forbidden_network)
            try:
                async with httpx.AsyncClient(transport=transport) as client:
                    url = "http://" + name + ".terminal/mcp"
                    self.assertEqual((await client.post(url, content=b"{}")).status_code, 200)
                    path.chmod(0o666)
                    with self.assertRaises(httpx.ConnectError):
                        await client.post(url, content=b"{}")
                    path.chmod(0o600)
                    for invalid in [url + "?leak=1", url.replace(name, "foreign"), url.replace("/mcp", "/control")]:
                        with self.assertRaises(httpx.ConnectError):
                            await client.post(invalid, content=b"{}")
            finally:
                server.close()
                await server.wait_closed()

    @unittest.skipUnless(os.geteuid() == 0 if hasattr(os, "geteuid") else False, "Rootless namespace UID 0 required")
    async def test_initializer_refuses_symlink_or_writable_runtime(self):
        with tempfile.TemporaryDirectory() as root:
            name = "briareus-" + "b" * 48
            initialize_runtime(root, name)
            initialize_runtime(root, name)
            directory = Path(root) / "workers" / name
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
            directory.chmod(0o777)
            with self.assertRaises(ValueError):
                initialize_runtime(root, name)
            directory.chmod(0o700)
            with self.assertRaises(ValueError):
                initialize_runtime(root, "../foreign")
            other = "briareus-" + "c" * 48
            (Path(root) / "workers" / other).symlink_to(directory, target_is_directory=True)
            with self.assertRaises(OSError):
                initialize_runtime(root, other)
