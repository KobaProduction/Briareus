"""Actual private Unix routing for each fixed supervisor module; no engine."""
from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import httpx

from node_agent.dataplane import worker_target
from node_agent.runtime_profiles import SUPERVISOR_MODULES
from node_agent.worker_transport import WorkerTransport
from node_agent.workspace_runtime import initializer_config
from node_protocol import WorkspaceMount
from uuid import uuid4
from test_reconciliation import fixture


class FixedRoutingTests(unittest.TestCase):
    def test_initializer_prepares_private_runtime_link_for_all_supervisors_only(self):
        _, base = fixture()
        base = base.model_copy(update={"workspace": WorkspaceMount(id=uuid4())})
        for module in SUPERVISOR_MODULES | {"files"}:
            spec = base.model_copy(update={"release": base.release.model_copy(update={"module": module})})
            helper = initializer_config(spec, "registry.example/node@sha256:" + "a" * 64)
            runtime = [value for value in helper["Env"] if value.startswith("BRIAREUS_RUNTIME_WORKER=")]
            if module in SUPERVISOR_MODULES:
                self.assertEqual(runtime, ["BRIAREUS_RUNTIME_WORKER=" + spec.container_name])
                self.assertEqual(helper["HostConfig"]["Binds"],
                    [f"/var/lib/briareus/nodes/{spec.node_uuid}/gateway:/node-link:rw"])
            else:
                self.assertEqual(runtime, [])
                self.assertNotIn("Binds", helper["HostConfig"])

    def test_only_files_uses_tcp_and_all_other_modules_use_fixed_unix_suffix(self):
        name = "briareus-" + "a" * 48
        for module in SUPERVISOR_MODULES:
            self.assertEqual(worker_target(SimpleNamespace(module=module, container_name=name)),
                             "http://" + name + "." + module + "/mcp")
        self.assertEqual(worker_target(SimpleNamespace(module="files", container_name=name, port=8000)),
                         "http://" + name + ":8000/mcp")
        with self.assertRaises(ValueError):
            worker_target(SimpleNamespace(module="foreign", container_name=name))


@unittest.skipUnless(hasattr(asyncio, "start_unix_server"), "Linux private Unix sockets required")
class SupervisorTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_supervisor_is_private_and_has_no_tcp_fallback(self):
        with tempfile.TemporaryDirectory() as root:
            name = "briareus-" + "b" * 48
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
            await transport.network.aclose()
            network_requests = []
            def network(request):
                network_requests.append(request)
                return httpx.Response(200, json={"fixture": "files-tcp"})
            transport.network = httpx.MockTransport(network)
            try:
                async with httpx.AsyncClient(transport=transport) as client:
                    for module in SUPERVISOR_MODULES:
                        url = "http://" + name + "." + module + "/mcp"
                        self.assertEqual((await client.post(url, content=b"{}")).status_code, 200)
                        path.chmod(0o666)
                        with self.assertRaises(httpx.ConnectError):
                            await client.post(url, content=b"{}")
                        path.chmod(0o600)
                    for url in ("http://" + name + ".foreign/mcp", "http://foreign.web/mcp",
                                "http://" + name + ".web.other/mcp", "http://" + name + ".web:8000/mcp",
                                "http://" + name + ".web/mcp?leak=1", "http://" + name + ".web/control"):
                        with self.assertRaises(httpx.ConnectError):
                            await client.post(url, content=b"{}")
                    self.assertEqual(network_requests, [])
                    self.assertEqual((await client.post("http://" + name + ":8000/mcp", content=b"{}")).status_code, 200)
                    self.assertEqual(len(network_requests), 1)
            finally:
                server.close()
                await server.wait_closed()
