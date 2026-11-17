"""Offline Rust Valkey discovery lease compatibility, no production services."""
from __future__ import annotations

import asyncio
import json
import os
import socket
import unittest
from pathlib import Path

import httpx

BINARY = Path(__file__).resolve().parents[1] / "target/debug/briareus-signoz-rust"
SECRET = "fixture-valkey-secret"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class DiscoveryContract(unittest.IsolatedAsyncioTestCase):
    async def test_real_resp_auth_inventory_renewal_and_withdraw(self) -> None:
        received: list[tuple[str, ...]] = []

        async def on_valkey(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                while not reader.at_eof():
                    line = await reader.readline()
                    if not line:
                        break
                    size = int(line[1:])
                    argv = []
                    for _ in range(size):
                        count = int((await reader.readline())[1:])
                        argv.append((await reader.readexactly(count)).decode())
                        assert await reader.readexactly(2) == b"\r\n"
                    if argv[0] == "AUTH":
                        assert argv == ["AUTH", "default", SECRET]
                        writer.write(b"+OK\r\n")
                    elif argv[0] == "SET":
                        received.append(tuple(argv[1:]))
                        writer.write(b"+OK\r\n")
                    elif argv[0] == "DEL":
                        received.append(("DEL", argv[1]))
                        writer.write(b":1\r\n")
                    else:
                        raise AssertionError("unexpected Valkey opcode")
                    await writer.drain()
            except (ConnectionError, asyncio.IncompleteReadError):
                pass
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(on_valkey, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        bind_port = free_port()
        env = {
            **os.environ,
            "BRIAREUS_SERVICE_TOKEN": "synthetic-panel-token",
            "CONTROL_PANEL_URL": "http://127.0.0.1:1",
            "RUST_MCP_DISCOVERY_ENABLED": "true",
            "VALKEY_URL": f"redis://127.0.0.1:{port}/0",
            "VALKEY_USERNAME": "default",
            "VALKEY_PASSWORD": SECRET,
            "VALKEY_NAMESPACE": "briareus:v1",
            "DEPLOYMENT_ENVIRONMENT": "production",
            "PORT": str(bind_port),
            "PRIVATE_MCP_ALLOWED_HOSTS": "127.0.0.1:*",
        }
        process = await asyncio.create_subprocess_exec(
            str(BINARY), env=env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=1) as client:
                for _ in range(100):
                    if process.returncode is not None:
                        self.fail("Rust discovery server exited before readiness")
                    try:
                        response = await client.get(
                            f"http://127.0.0.1:{bind_port}/health/discovery"
                        )
                        if response.status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    await asyncio.sleep(0.05)
                else:
                    self.fail("Rust discovery health readiness timed out")
            self.assertEqual(response.json(), {
                "service": {"id": "signoz", "name": "SigNoz", "group": "observability"},
                "environment": "production", "ready": True,
            })
            self.assertTrue(any(row[0].endswith(":inventory:signoz") for row in received))
            leases = [
                row for row in received
                if row[0].startswith("briareus:v1:services:production:lease:signoz:")
            ]
            self.assertTrue(leases)
            self.assertEqual(leases[0][1:], ("1", "EX", "20"))
            inventory = next(row[1] for row in received if row[0].endswith(":inventory:signoz"))
            self.assertEqual(
                json.loads(inventory),
                {"id": "signoz", "name": "SigNoz", "group": "observability"},
            )
            await asyncio.sleep(5.2)
            self.assertGreaterEqual(sum(row[0] == leases[0][0] for row in received), 2)
        finally:
            process.terminate()
            await asyncio.wait_for(process.wait(), timeout=6)
            server.close()
            await server.wait_closed()
            await asyncio.sleep(0.05)
        self.assertTrue(any(row == ("DEL", leases[0][0]) for row in received))


if __name__ == "__main__":
    unittest.main()
