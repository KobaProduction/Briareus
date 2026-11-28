"""Compare V1 Python discovery with local Rust Gateway against a synthetic Valkey."""

from __future__ import annotations

import asyncio
import json
import socket
import sys
import unittest
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import uvicorn
from fixture_server import FixtureServer
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

ROOT = Path(__file__).resolve().parents[3]
for directory in (
    "shared/services/catalog/src",
    "shared/services/discovery/src",
    "shared/cache/src",
    "shared/python/environment-models/src",
    "shared/python/environment-parsing/src",
):
    sys.path.insert(0, str(ROOT / directory))

from briareus_service_catalog import ServiceDefinition  # noqa: E402
from briareus_service_discovery import ServiceDiscovery  # noqa: E402

BINARY = ROOT / "services/gateway-rust/target/debug/briareus-gateway-rust"

GITHUB = ServiceDefinition(id="github", name="GitHub", group="svc")
CUSTOM = ServiceDefinition(id="custom-provider", name="Custom Provider", group="plugins")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class MockRegistry:
    environment = "test"

    def inventory(self) -> tuple[ServiceDefinition, ...]:
        return (GITHUB, CUSTOM)

    def active_services(self) -> frozenset[str]:
        return frozenset(("github", "custom-provider"))

    def close(self) -> None:
        pass


async def redis_connection(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while not reader.at_eof():
            line = await reader.readline()
            if not line:
                break
            assert line.startswith(b"*")
            size = int(line[1:])
            args: list[str] = []
            for _ in range(size):
                size_bytes = await reader.readline()
                assert size_bytes.startswith(b"$")
                n = int(size_bytes[1:])
                data = await reader.readexactly(n + 2)
                assert data.endswith(b"\r\n")
                args.append(data[:-2].decode())
            if args[0] == "AUTH":
                assert args == ["AUTH", "default", "fixture-password"]
                answer = b"+OK\r\n"
            elif args[0] == "SCAN":
                assert len(args) == 6 and args[1] == "0"
                kind = "inventory" if "inventory" in args[3] else "lease"
                if kind == "lease":
                    keys = [
                        "briareus:v1:services:test:lease:github:0123456789abcdef",
                        "briareus:v1:services:test:lease:custom-provider:abcdef0123456789",
                    ]
                else:
                    keys = [
                        "briareus:v1:services:test:inventory:github",
                        "briareus:v1:services:test:inventory:custom-provider",
                    ]
                answer = b"*2\r\n$1\r\n0\r\n" + f"*{len(keys)}\r\n".encode()
                for key in keys:
                    answer += f"${len(key)}\r\n{key}\r\n".encode()
            elif args[0] == "GET":
                requested = args[1].rsplit(":", 1)[-1]
                source = GITHUB if requested == "github" else CUSTOM
                data = source.model_dump_json().encode()
                answer = f"${len(data)}\r\n".encode() + data + b"\r\n"
            else:
                raise AssertionError("Unexpected Redis opcode")
            writer.write(answer)
            await writer.drain()
    except (ConnectionError, asyncio.IncompleteReadError):
        pass
    finally:
        writer.close()
        await writer.wait_closed()


@asynccontextmanager
async def provider_fixture(service: ServiceDefinition, *, environment: str) -> AsyncIterator[str]:
    async def health(_: Request) -> JSONResponse:
        return JSONResponse(
            {
                "service": service.model_dump(),
                "environment": environment,
                "ready": True,
            }
        )

    port = free_port()
    app = Starlette(routes=[Route("/health/discovery", health)])
    server = FixtureServer(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="error",
            lifespan="off",
            access_log=False,
        )
    )
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.025)
        else:
            raise RuntimeError("Provider fixture not ready")
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 6)


class GatewayDiscoveryContracts(unittest.IsolatedAsyncioTestCase):
    async def test_valkey_lease_and_real_readiness_match_python(self) -> None:
        redis_server = await asyncio.start_server(redis_connection, "127.0.0.1", 0)
        redis_port = redis_server.sockets[0].getsockname()[1]
        try:
            async with (
                provider_fixture(GITHUB, environment="test") as github,
                provider_fixture(CUSTOM, environment="different") as custom,
            ):
                # Python can route fake internal hostnames through its HTTP transport.
                def python_probe(request: httpx.Request) -> httpx.Response:
                    host = request.url.host
                    identity = GITHUB if host == "github-mcp-hand" else CUSTOM
                    environment = "test" if identity == GITHUB else "different"
                    return httpx.Response(
                        200,
                        json={
                            "service": identity.model_dump(),
                            "environment": environment,
                            "ready": True,
                        },
                    )

                client = httpx.AsyncClient(
                    transport=httpx.MockTransport(python_probe),
                    trust_env=False,
                )
                python = ServiceDiscovery(MockRegistry(), client=client)  # type: ignore[arg-type]
                try:
                    actual = await python.snapshot()
                finally:
                    await python.close()
                connected = {item.id for item in actual.services if item.connected}
                self.assertEqual(connected, {"github"})
                port = free_port()
                env = {
                    "RUST_GATEWAY_SHADOW_ONLY": "true",
                    "BIND_HOST": "127.0.0.1",
                    "PORT": str(port),
                    "BRIAREUS_NODE_ID": "fixture",
                    "CONTROL_PANEL_URL": "http://127.0.0.1:1",
                    "CONTROL_PANEL_UI_URL": "http://127.0.0.1:1",
                    "VALKEY_URL": f"redis://127.0.0.1:{redis_port}/0",
                    "VALKEY_USERNAME": "default",
                    "VALKEY_PASSWORD": "fixture-password",
                    "VALKEY_NAMESPACE": "briareus:v1",
                    "DEPLOYMENT_ENVIRONMENT": "test",
                    "GATEWAY_SHADOW_TARGETS_JSON": json.dumps(
                        {
                            "github": github,
                            "custom-provider": custom,
                        }
                    ),
                }
                env.pop("OIDC_ISSUER_URL", None)
                process = await asyncio.create_subprocess_exec(
                    str(BINARY),
                    env=env,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                try:
                    async with httpx.AsyncClient(trust_env=False, timeout=10) as http:
                        for _ in range(150):
                            try:
                                r = await http.get(f"http://127.0.0.1:{port}/health")
                                if r.status_code == 200:
                                    break
                            except httpx.HTTPError:
                                pass
                            if process.returncode is not None:
                                self.fail("Rust process exited before readiness")
                            await asyncio.sleep(0.025)
                        else:
                            self.fail("Rust Gateway did not start")
                        for path, code in [
                            ("/svc/github/mcp", 401),
                            ("/observability/signoz/mcp", 503),
                            ("/plugins/custom-provider/mcp", 503),
                            ("/svc/nonexistent/mcp", 404),
                        ]:
                            response = await http.post(f"http://127.0.0.1:{port}{path}")
                            with self.subTest(path=path):
                                self.assertEqual(response.status_code, code)
                        redis_server.close()
                        await redis_server.wait_closed()
                        # Cached membership expires in five seconds; outage fails closed.
                        await asyncio.sleep(5.2)
                        response = await http.post(f"http://127.0.0.1:{port}/svc/github/mcp")
                        self.assertEqual(response.status_code, 503)
                finally:
                    process.terminate()
                    await asyncio.wait_for(process.wait(), 6)
        finally:
            redis_server.close()
            await redis_server.wait_closed()


if __name__ == "__main__":
    unittest.main()
