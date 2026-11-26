"""Start real Gateway/API entrypoints on isolated loopback sockets, without Docker."""

from __future__ import annotations

import base64
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from collections.abc import Iterator
from contextlib import AbstractContextManager, ExitStack, contextmanager
from pathlib import Path
from urllib.parse import parse_qs

import httpx
from cryptography.fernet import Fernet
from websockets.sync.client import connect
from zitadel_test_support import ZitadelTokenFixture

ROOT = Path(__file__).resolve().parents[3]
SERVICE_TOKEN = "synthetic-runtime-service-token"
PROVISIONER = "synthetic-runtime-provisioner"
BROWSER_CLIENT = "registered-public-client"
RESOURCE_CLIENT = "runtime-resource"
RESOURCE_SECRET = "synthetic-runtime-resource-secret"
# Override only the transport origin at the API composition root, using the
# existing client constructor. All real startup, HTTP and authorization code runs.
API_ENTRYPOINT = """
import sys
import uvicorn
from functools import partial
from unittest.mock import patch
from control_panel_api.infrastructure.gateway_identity import GatewayIdentityClient
with patch('control_panel_api.infrastructure.gateway_identity.GatewayIdentityClient',
           partial(GatewayIdentityClient, origin=f'http://127.0.0.1:{sys.argv[1]}')):
    from control_panel_api.runtime import app
uvicorn.run(app, host='127.0.0.1', port=int(sys.argv[2]),
            access_log=False, log_level='warning')
"""


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def base_url(port: int) -> str:
    return f"http://127.0.0.1:{port}"


class RuntimeAuthority(ZitadelTokenFixture):
    def __init__(self) -> None:
        super().__init__()
        self.role_exists = False
        self.creates = 0
        self.lookups = 0
        self.provisioning_status = 200
        self.opaque_token = "synthetic-opaque-user"
        fixture = self
        # Reuse the real test provider's discovery, JWKS and signed-token factory.
        parent = self.server.RequestHandlerClass

        class Handler(parent):  # type: ignore[valid-type,misc]
            def reply(self, status: int, data: object) -> None:
                body = json.dumps(data).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length)
                if self.path == "/introspect":
                    fixture.introspection_requests += 1
                    expected = base64.b64encode(
                        f"{RESOURCE_CLIENT}:{RESOURCE_SECRET}".encode()
                    ).decode()
                    if self.headers.get("Authorization") != "Basic " + expected:
                        self.reply(401, {})
                        return
                    token = parse_qs(raw.decode()).get("token", [])
                    self.reply(
                        fixture.introspection_status,
                        fixture.introspection_payload
                        if token == [fixture.opaque_token]
                        else {"active": False},
                    )
                    return
                if self.headers.get("Authorization") != "Bearer " + PROVISIONER:
                    self.reply(403, {})
                    return
                if fixture.provisioning_status != 200:
                    self.reply(fixture.provisioning_status, {})
                    return
                project = fixture.settings.audience
                body = json.loads(raw)
                if self.path.endswith("/ListProjectRoles") and body == {
                    "projectId": project,
                    "filters": [
                        {"roleKeyFilter": {"key": "access", "method": "TEXT_FILTER_METHOD_EQUALS"}}
                    ],
                }:
                    fixture.lookups += 1
                    self.reply(
                        200,
                        {
                            "projectRoles": [{"projectId": project, "key": "access"}]
                            if fixture.role_exists
                            else []
                        },
                    )
                elif self.path.endswith("/AddProjectRole") and body == {
                    "projectId": project,
                    "roleKey": "access",
                    "displayName": "Access",
                    "group": "Nodes",
                }:
                    fixture.creates += 1
                    fixture.role_exists = True
                    self.reply(200, {"creationDate": "2026-11-01T00:00:00Z"})
                else:
                    self.reply(400, {})

        self.server.RequestHandlerClass = Handler


def fixture_env(directory: Path, cache_port: int) -> dict[str, str]:
    # Do not inherit runtime credentials, proxy variables or ambient dotenv data.
    env = {
        key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "TEMP", "TMP") if key in os.environ
    }
    env.update(
        {
            "PYTHONPATH": os.pathsep.join(str(Path(p).resolve()) for p in sys.path if p),
            "PYTHONUNBUFFERED": "1",
            "HOME": str(directory),
            "DEPLOYMENT_ENVIRONMENT": "test",
            "BRIAREUS_SERVICE_TOKEN": SERVICE_TOKEN,
            "VALKEY_URL": f"redis://127.0.0.1:{cache_port}/0",
            "VALKEY_PASSWORD": "synthetic-cache-password",
            "VALKEY_NAMESPACE": "briareus:runtime-test",
            "SERVER_MOUNT_PATH": str(directory / "workspace"),
        }
    )
    return env


@contextmanager
def process(
    command: list[str], env: dict[str, str], port: int
) -> Iterator[subprocess.Popen[bytes]]:
    with tempfile.TemporaryFile() as log:
        child = subprocess.Popen(
            command,
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            with httpx.Client(timeout=0.5, trust_env=False) as client:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if child.poll() is not None:
                        break
                    try:
                        if client.get(base_url(port) + "/health").status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.05)
                else:
                    raise AssertionError("Native runtime readiness timed out")
                if child.poll() is not None:
                    log.seek(0)
                    raise AssertionError(log.read()[-6000:].decode(errors="replace"))
            yield child
        except BaseException:
            log.seek(0)
            print(log.read()[-6000:].decode(errors="replace"), file=sys.stderr)
            raise
        finally:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)


class GatewayRuntimeContracts(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory(prefix="briareus-native-runtime-")
        self.addCleanup(self.directory.cleanup)
        self.provider = RuntimeAuthority()
        self.addCleanup(self.provider.close)
        self.gateway_port = free_port()
        self.api_port = free_port()
        # Reserve an unavailable cache port: this exercises actual degraded-mode
        # behavior, not a simulated successful Valkey server.
        self.cache_socket = socket.socket()
        self.cache_socket.bind(("127.0.0.1", 0))
        self.addCleanup(self.cache_socket.close)
        self.root = Path(self.directory.name)
        self.common = fixture_env(self.root, self.cache_socket.getsockname()[1])
        self.api_env = {
            **self.common,
            "CONTROL_PANEL_DATABASE_BACKEND": "sqlite",
            "CONTROL_PANEL_SQLITE_PATH": str(self.root / "api.sqlite3"),
            "CONTROL_PANEL_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        }
        source = self.provider.settings
        self.gateway_env = {
            **self.common,
            "CONTROL_PANEL_URL": base_url(self.api_port),
            "MCP_PUBLIC_BASE_URL": base_url(self.gateway_port),
            "BRIAREUS_NODE_ID": source.node_id,
            "OIDC_ISSUER_URL": source.issuer_url,
            "OIDC_AUDIENCE": source.audience,
            "OIDC_ROLES_CLAIM_PATH": json.dumps(source.roles_claim_path),
            "OIDC_ROLES_FORMAT": source.roles_format,
            "OIDC_ROLES_ORGANIZATION_ID": source.roles_organization_id,
            "OIDC_BROWSER_CLIENT_ID": BROWSER_CLIENT,
            "OIDC_PROVISIONING_TOKEN": PROVISIONER,
        }

    def gateway(self, mode: str = "jwt") -> AbstractContextManager[subprocess.Popen[bytes]]:
        env = dict(self.gateway_env)
        env["OIDC_TOKEN_VERIFICATION"] = mode
        if mode == "introspection":
            env.update({"OIDC_CLIENT_ID": RESOURCE_CLIENT, "OIDC_CLIENT_SECRET": RESOURCE_SECRET})
        binary = os.environ.get("BRIAREUS_TEST_GATEWAY_BINARY")
        if binary:
            env.update(
                {
                    "RUST_GATEWAY_SHADOW_ONLY": "true",
                    "BIND_HOST": "127.0.0.1",
                    "PORT": str(self.gateway_port),
                    "CONTROL_PANEL_UI_URL": "http://127.0.0.1:1",
                }
            )
            command = [binary]
        else:
            command = [
                sys.executable,
                "-m",
                "uvicorn",
                "gateway.server:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.gateway_port),
                "--no-access-log",
                "--log-level",
                "warning",
            ]
        return process(command, env, self.gateway_port)

    def api(self) -> AbstractContextManager[subprocess.Popen[bytes]]:
        self.assertFalse(any(k.startswith("OIDC_") for k in self.api_env))
        return process(
            [sys.executable, "-c", API_ENTRYPOINT, str(self.gateway_port), str(self.api_port)],
            self.api_env,
            self.api_port,
        )

    def assert_identity(self, caller: httpx.Client, token: str) -> None:
        result = caller.get("/api/identity", headers={"Authorization": "Bearer " + token})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["subject"], "user-1")

    def assert_websocket(self, token: str) -> None:
        with connect(
            f"ws://127.0.0.1:{self.gateway_port}/api/realtime",
            origin=base_url(self.gateway_port),
            subprotocols=["briareus.v1", "bearer." + token],
            open_timeout=5,
            close_timeout=2,
            proxy=None,
        ) as ws:
            self.assertEqual(json.loads(ws.recv(timeout=5))["type"], "ready")
            ws.send('{"type":"ping"}')
            self.assertEqual(json.loads(ws.recv(timeout=5))["type"], "pong")

    def assert_jwt_routes(self, public: httpx.Client, token: str) -> None:
        config = public.get("/api/identity/config")
        self.assertEqual(config.status_code, 200)
        self.assertEqual(config.json()["client_id"], BROWSER_CLIENT)
        self.assert_identity(public, token)
        self.assertEqual(public.get("/api/identity").status_code, 401)
        for headers in (
            {"X-Briareus-Principal": "forged"},
            {"Authorization": "Bearer " + SERVICE_TOKEN},
        ):
            self.assertEqual(public.get("/api/identity", headers=headers).status_code, 401)
        bootstrap = public.get("/api/bootstrap", headers={"Authorization": "Bearer " + token})
        self.assertEqual(bootstrap.status_code, 200)
        self.assertEqual(bootstrap.json()["node"]["id"], "access")
        self.assert_websocket(token)

    def test_native_jwt_runtime_recovers_after_gateway_restart(self) -> None:
        token = self.provider.token()
        headers = {"Authorization": "Bearer " + token}
        with (
            ExitStack() as api_stack,
            httpx.Client(
                base_url=base_url(self.gateway_port), timeout=12, trust_env=False
            ) as public,
            httpx.Client(base_url=base_url(self.api_port), timeout=12, trust_env=False) as direct,
        ):
            with self.gateway():
                api_process = api_stack.enter_context(self.api())
                self.assert_jwt_routes(public, token)
            # API stays alive when its sole identity authority is unavailable.
            self.assertIsNone(api_process.poll())
            self.assertEqual(direct.get("/health").status_code, 200)
            self.assertEqual(direct.get("/admin/api/identity", headers=headers).status_code, 503)
            with self.gateway():
                self.assert_identity(public, token)
                self.assert_websocket(token)
                self.assertIsNone(api_process.poll())
                # Restart API against the same isolated SQLite database.
                api_stack.close()
                api_stack.enter_context(self.api())
                self.assert_identity(public, token)
        self.assertTrue((self.root / "api.sqlite3").is_file())
        if not os.environ.get("BRIAREUS_TEST_GATEWAY_BINARY"):
            self.assertEqual((self.provider.lookups, self.provider.creates), (2, 1))

    def test_native_introspection_runtime_and_provider_failure(self) -> None:
        now = int(time.time())
        source = self.provider.settings
        self.provider.introspection_payload = {
            "active": True,
            "iss": source.issuer_url,
            "aud": source.audience,
            "sub": "user-1",
            "client_id": BROWSER_CLIENT,
            "exp": now + 120,
            "iat": now - 1,
            source.roles_claim_path[0]: {
                "access": {source.roles_organization_id: "example.test"},
            },
        }
        with (
            self.gateway("introspection"),
            self.api(),
            httpx.Client(
                base_url=base_url(self.gateway_port),
                timeout=12,
                trust_env=False,
            ) as public,
        ):
            self.assert_identity(public, self.provider.opaque_token)
            self.assert_websocket(self.provider.opaque_token)
            self.assertEqual(self.provider.introspection_requests, 1)
            self.assertEqual(
                public.get(
                    "/api/identity", headers={"Authorization": "Bearer invalid-opaque"}
                ).status_code,
                401,
            )
            self.provider.introspection_status = 503
            self.assertEqual(
                public.get(
                    "/api/identity", headers={"Authorization": "Bearer fresh-opaque"}
                ).status_code,
                503,
            )
