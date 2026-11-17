"""Cryptographic OIDC JWT and role-contract comparison: isolated issuer, no live credentials."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import socket
import sys
import time
import unittest
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import jwt
import uvicorn
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "shared/identity/token-verification/src"))
sys.path.insert(0, str(ROOT / "shared/python/environment-models/src"))
sys.path.insert(0, str(ROOT / "shared/python/environment-parsing/src"))
sys.path.insert(0, str(ROOT / "shared/contracts/json-values/src"))
from briareus_oidc import OidcTokenSettings, OidcTokenVerifier, TokenVerificationError  # noqa: E402

BINARY = ROOT / "services/gateway-rust/target/debug/briareus-gateway-rust"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def b64(number: int) -> str:
    value = number.to_bytes((number.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


@asynccontextmanager
async def issuer_fixture(
    introspection_replies: dict[str, dict[str, object]] | None = None,
) -> AsyncIterator[tuple[str, bytes]]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = key.public_key().public_numbers()
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    jwks = {
        "keys": [
            {
                "kty": "RSA",
                "kid": "fixture-key-1",
                "alg": "RS256",
                "use": "sig",
                "n": b64(numbers.n),
                "e": b64(numbers.e),
            }
        ]
    }

    async def metadata(_: Request) -> JSONResponse:
        return JSONResponse(
            {
                "issuer": url,
                "jwks_uri": url + "/keys",
                "introspection_endpoint": url + "/introspect",
            }
        )

    async def keys(_: Request) -> JSONResponse:
        return JSONResponse(jwks)

    async def introspect(request: Request) -> JSONResponse:
        import base64 as _base64

        expected = _base64.b64encode(b"fixture+client:s3cret%2Bwith+space").decode()
        if request.headers.get("authorization") != "Basic " + expected:
            return JSONResponse({"error": "bad_fixture_credentials"}, status_code=401)
        data = await request.form()
        if data.get("token_type_hint") != "access_token":
            return JSONResponse({"error": "invalid_fixture_hint"}, status_code=400)
        token = data.get("token", "")
        payload = (introspection_replies or {}).get(str(token), {"active": False})
        return JSONResponse(payload)

    app = Starlette(
        routes=[
            Route("/.well-known/openid-configuration", metadata),
            Route("/keys", keys),
            Route("/introspect", introspect, methods=["POST"]),
        ]
    )
    server = uvicorn.Server(
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
        for _ in range(120):
            if server.started:
                break
            await asyncio.sleep(0.025)
        else:
            raise RuntimeError("OIDC fixture did not start")
        yield url, pem
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 6)


@asynccontextmanager
async def rust_gateway(
    issuer: str,
    roles_format: str,
    role_path: str,
    organization: str,
    *,
    targets: dict[str, str] | None = None,
    panel_url: str = "http://127.0.0.1:1",
    verification_mode: str = "jwt",
) -> AsyncIterator[tuple[httpx.AsyncClient, str]]:
    port = free_port()
    env = {
        **os.environ,
        "RUST_GATEWAY_SHADOW_ONLY": "true",
        "BIND_HOST": "127.0.0.1",
        "PORT": str(port),
        "BRIAREUS_NODE_ID": "tambov",
        "CONTROL_PANEL_URL": panel_url,
        "CONTROL_PANEL_UI_URL": "http://127.0.0.1:1",
        "OIDC_ISSUER_URL": issuer,
        "OIDC_AUDIENCE": "fixture-project",
        "MCP_PUBLIC_BASE_URL": "https://briareus.example",
        "OIDC_ROLES_CLAIM_PATH": role_path,
        "OIDC_ROLES_FORMAT": roles_format,
        "OIDC_ROLES_ORGANIZATION_ID": organization,
        "OIDC_JWT_ALGORITHMS": "RS256",
        "OIDC_TOKEN_VERIFICATION": verification_mode,
        "OIDC_INTROSPECTION_CLIENT_ID": "fixture client",
        "OIDC_INTROSPECTION_CLIENT_SECRET": "s3cret+with space",
        "GATEWAY_SHADOW_TARGETS_JSON": json.dumps(targets or {}),
    }
    proc = await asyncio.create_subprocess_exec(
        str(BINARY),
        env=env,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=8) as client:
            for _ in range(150):
                try:
                    r = await client.get(f"http://127.0.0.1:{port}/health")
                    if r.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if proc.returncode is not None:
                    raise RuntimeError("Rust OIDC shadow exited before startup")
                await asyncio.sleep(0.025)
            else:
                raise RuntimeError("Rust OIDC shadow startup timed out")
            yield client, f"http://127.0.0.1:{port}/observability/signoz/mcp"
    finally:
        proc.terminate()
        await asyncio.wait_for(proc.wait(), 6)


class OidcContract(unittest.IsolatedAsyncioTestCase):
    async def test_signed_jwt_matches_python_authority_and_rejects_bad_claims(self) -> None:
        async with issuer_fixture() as (issuer, pem):
            now = int(time.time())
            roles_key = "urn:zitadel:iam:org:project:fixture-project:roles"
            for mode, path, organization in [
                ("list", '["roles"]', ""),
                ("organization_grants", f'["{roles_key}"]', "fixture-org"),
            ]:
                role_claims = (
                    {"roles": ["tambov"]}
                    if mode == "list"
                    else {roles_key: {"tambov": {"fixture-org": "fixture-project"}}}
                )
                settings = OidcTokenSettings(
                    issuer_url=issuer,
                    audience="fixture-project",
                    required_role="tambov",
                    roles_claim_path=("roles",) if mode == "list" else (roles_key,),
                    roles_format=mode,
                    roles_organization_id=organization,
                )
                python = OidcTokenVerifier(settings)
                async with rust_gateway(issuer, mode, path, organization) as (client, endpoint):
                    metadata = await client.get(
                        endpoint.replace(
                            "/observability/signoz/mcp",
                            "/.well-known/oauth-protected-resource/observability/signoz/mcp",
                        )
                    )
                    self.assertEqual(metadata.status_code, 200)
                    self.assertEqual(
                        metadata.json(),
                        {
                            "resource": "https://briareus.example/observability/signoz/mcp",
                            "authorization_servers": [issuer],
                            "scopes_supported": ["openid", "profile", "email", "offline_access"],
                            "bearer_methods_supported": ["header"],
                            "resource_name": "Briareus SigNoz",
                        },
                    )
                    challenge = await client.get(endpoint)
                    self.assertEqual(challenge.status_code, 401)
                    self.assertEqual(
                        challenge.headers.get("www-authenticate"),
                        'Bearer scope="openid profile email offline_access", '
                        'resource_metadata="https://briareus.example/.well-known/'
                        'oauth-protected-resource/observability/signoz/mcp"',
                    )
                    base = {
                        "iss": issuer,
                        "aud": "fixture-project",
                        "sub": "fixture-user",
                        "client_id": "fixture-client",
                        "exp": now + 240,
                        "iat": now - 10,
                        "scope": "openid offline_access",
                        **role_claims,
                    }
                    variants = [
                        ("valid", {}, True),
                        ("expired", {"exp": now - 10}, False),
                        ("future_nbf", {"nbf": now + 300}, False),
                        ("future_iat", {"iat": now + 300}, False),
                        ("wrong_issuer", {"iss": "https://untrusted.invalid"}, False),
                        ("wrong_audience", {"aud": "different-project"}, False),
                        (
                            "wrong_role",
                            {"roles": ["access"]}
                            if mode == "list"
                            else {roles_key: {"tambov": {"other-org": "fixture-project"}}},
                            False,
                        ),
                        ("wrong_azp", {"azp": "different-client"}, False),
                        ("no_client", {"client_id": None}, False),
                    ]
                    for label, updates, should_pass in variants:
                        claims = {**base, **updates}
                        if claims.get("client_id") is None:
                            claims.pop("client_id", None)
                        token = jwt.encode(
                            claims, pem, algorithm="RS256", headers={"kid": "fixture-key-1"}
                        )
                        try:
                            await asyncio.to_thread(python.verify, token)
                            python_pass = True
                        except TokenVerificationError:
                            python_pass = False
                        response = await client.post(
                            endpoint, headers={"Authorization": "Bearer " + token}
                        )
                        rust_pass = response.status_code not in (401, 403)
                        with self.subTest(mode=mode, token=label):
                            self.assertEqual(python_pass, should_pass)
                            self.assertEqual(rust_pass, python_pass)
                            if not should_pass:
                                self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
