"""Bounded parallel MCP session isolation against a synthetic local Hand.

No Docker, actual provider tokens, public Gateway or production network.
"""

from __future__ import annotations

import asyncio
import sys
import time
import unittest
from pathlib import Path

import httpx
import jwt

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_mcp_parity import InitializeFault, provider_fixture, rpc  # noqa: E402
from check_oidc_parity import issuer_fixture, rust_gateway  # noqa: E402
from check_python_mcp_parity import initialized_client  # noqa: E402


def signed_token(
    issuer: str,
    signing_key: bytes,
    *,
    subject: str = "owner",
    client_id: str = "client-a",
    lifetime: int = 120,
) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "iss": issuer,
            "aud": "fixture-project",
            "sub": subject,
            "client_id": client_id,
            "iat": now - 1,
            "exp": now + lifetime,
            "roles": ["tambov"],
        },
        signing_key,
        algorithm="RS256",
        headers={"kid": "fixture-key-1"},
    )


class ConcurrentMcpSessions(unittest.IsolatedAsyncioTestCase):
    async def test_multiple_independent_sessions_share_backend_without_leaking_results(
        self,
    ) -> None:
        async with (
            issuer_fixture() as (issuer, signing_key),
            provider_fixture("GitHub Synthetic") as (github_url, _provider),
            rust_gateway(issuer, "list", '["roles"]', "", targets={"github": github_url}) as (
                client,
                signoz_path,
            ),
        ):
            path = signoz_path.replace("/observability/signoz/mcp", "/svc/github/mcp")
            bearer = signed_token(
                issuer,
                signing_key,
                subject="synthetic-user",
                client_id="synthetic-client",
                lifetime=240,
            )
            clients = await asyncio.gather(
                *(initialized_client(client, path, bearer) for _ in range(6))
            )
            session_ids = [h.get("Mcp-Session-Id") for h in clients]
            self.assertTrue(all(session_ids), session_ids)
            self.assertEqual(len(set(session_ids)), len(session_ids))

            async def call(index: int, item: int) -> tuple[int, int, int, object]:
                response = await client.post(
                    path,
                    headers=clients[index],
                    json={
                        "jsonrpc": "2.0",
                        "id": index * 100 + item + 2,
                        "method": "tools/call",
                        "params": {
                            "name": "add_numbers",
                            "arguments": {"left": index * 1000 + item, "right": 9},
                        },
                    },
                )
                return index, item, response.status_code, rpc(response)

            # Six frontends and 48 interleaved requests with the same two-slot
            # backend pool. One client's JSON-RPC IDs must never become another's.
            async with asyncio.timeout(30):
                results = await asyncio.gather(
                    *(call(index, item) for index in range(6) for item in range(8))
                )
            for index, item, status, body in results:
                with self.subTest(client=index, item=item):
                    self.assertEqual(status, 200)
                    self.assertEqual(body["id"], index * 100 + item + 2)
                    self.assertFalse(body["result"].get("isError", False))
                    self.assertEqual(
                        body["result"]["structuredContent"]["result"],
                        index * 1000 + item + 9,
                    )

            deleted = await client.delete(path, headers=clients[0])
            self.assertEqual(deleted.status_code, 200)
            stale = await client.post(
                path,
                headers=clients[0],
                json={"jsonrpc": "2.0", "id": 999, "method": "tools/list", "params": {}},
            )
            self.assertNotEqual(stale.status_code, 200)
            healthy = await asyncio.gather(*(call(index, 11) for index in range(1, 6)))
            for index, _, status, body in healthy:
                self.assertEqual(status, 200)
                self.assertEqual(body["result"]["structuredContent"]["result"], index * 1000 + 20)

            denial = await client.post(
                path,
                headers={**clients[1], "Authorization": "Bearer invalid"},
                json={"jsonrpc": "2.0", "id": 700, "method": "tools/list"},
            )
            self.assertEqual(denial.status_code, 401)

    async def test_session_owner_must_match_subject_and_client_even_with_valid_bearer(self) -> None:
        async with (
            issuer_fixture() as (issuer, signing_key),
            provider_fixture("GitHub Synthetic") as (github, _),
            rust_gateway(issuer, "list", '["roles"]', "", targets={"github": github}) as (
                client,
                endpoint,
            ),
        ):
            path = endpoint.replace("/observability/signoz/mcp", "/svc/github/mcp")

            def token(
                subject: str = "owner", client_id: str = "client-a", lifetime: int = 120
            ) -> str:
                return signed_token(
                    issuer,
                    signing_key,
                    subject=subject,
                    client_id=client_id,
                    lifetime=lifetime,
                )

            original = token()
            headers = await initialized_client(client, path, original)
            request = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
            for stranger in (token(subject="other-user"), token(client_id="client-b")):
                foreign = {**headers, "Authorization": "Bearer " + stranger}
                self.assertEqual(
                    (await client.post(path, headers=foreign, json=request)).status_code, 404
                )
                self.assertEqual((await client.get(path, headers=foreign)).status_code, 404)
                self.assertEqual((await client.delete(path, headers=foreign)).status_code, 404)

            # A replacement access token for the same identity does not force
            # the MCP client to create another session.
            renewed = {**headers, "Authorization": "Bearer " + token(lifetime=240)}
            self.assertNotEqual(renewed["Authorization"], headers["Authorization"])
            self.assertIn("result", rpc(await client.post(path, headers=renewed, json=request)))

            duplicate = httpx.Headers(headers)
            duplicate = httpx.Headers(
                [*duplicate.multi_items(), ("Authorization", "Bearer " + original)]
            )
            self.assertEqual(
                (await client.post(path, headers=duplicate, json=request)).status_code, 401
            )
            duplicate_session = httpx.Headers(
                [
                    *httpx.Headers(headers).multi_items(),
                    ("Mcp-Session-Id", headers["Mcp-Session-Id"]),
                ]
            )
            self.assertEqual(
                (await client.post(path, headers=duplicate_session, json=request)).status_code,
                400,
            )
            self.assertEqual((await client.delete(path, headers=renewed)).status_code, 200)
            self.assertEqual(
                (await client.post(path, headers=renewed, json=request)).status_code, 404
            )

    async def test_only_interrupted_backend_initialization_is_repeated_once(self) -> None:
        for failures in (1, 2):
            fault = InitializeFault(remaining=failures)
            async with (
                issuer_fixture() as (issuer, key),
                provider_fixture("GitHub Synthetic", initialize_fault=fault) as (github, _),
                rust_gateway(issuer, "list", '["roles"]', "", targets={"github": github}) as (
                    client,
                    endpoint,
                ),
            ):
                token = signed_token(issuer, key)
                path = endpoint.replace("/observability/signoz/mcp", "/svc/github/mcp")
                headers = await initialized_client(client, path, token)
                response = await client.post(
                    path,
                    headers=headers,
                    json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                )
                self.assertEqual(fault.attempts, 2)
                result = rpc(response)
                if failures == 1:
                    self.assertIn("result", result)
                else:
                    self.assertEqual(result["error"]["message"], "MCP backend unavailable")

    async def test_standalone_sse_requires_renewal_at_admitting_bearer_expiry(self) -> None:
        async with (
            issuer_fixture() as (issuer, key),
            provider_fixture("GitHub Synthetic") as (github, _),
            rust_gateway(issuer, "list", '["roles"]', "", targets={"github": github}) as (
                client,
                endpoint,
            ),
        ):
            path = endpoint.replace("/observability/signoz/mcp", "/svc/github/mcp")
            headers = await initialized_client(client, path, signed_token(issuer, key))
            short = {**headers, "Authorization": "Bearer " + signed_token(issuer, key, lifetime=3)}
            async with asyncio.timeout(6):
                async with client.stream("GET", path, headers=short) as response:
                    self.assertEqual(response.status_code, 200)
                    self.assertIn("text/event-stream", response.headers["content-type"])
                    async for _chunk in response.aiter_bytes():
                        pass
            rpc_request = {"jsonrpc": "2.0", "id": 9, "method": "tools/list", "params": {}}
            denied = await client.post(path, headers=short, json=rpc_request)
            self.assertEqual(denied.status_code, 401)
            self.assertIn("WWW-Authenticate", denied.headers)
            self.assertIn("result", rpc(await client.post(path, headers=headers, json=rpc_request)))
            self.assertEqual((await client.delete(path, headers=headers)).status_code, 200)

    async def test_session_capacity_is_bounded_and_delete_releases_capacity(self) -> None:
        async with (
            issuer_fixture() as (issuer, key),
            rust_gateway(issuer, "list", '["roles"]', "") as (client, endpoint),
        ):
            token = signed_token(issuer, key, lifetime=120)
            path = endpoint.replace("/observability/signoz/mcp", "/svc/github/mcp")
            sessions: list[dict[str, str]] = []
            async with asyncio.timeout(30):
                # Exercise the actual production-bound limit, without any real
                # provider or backend invocation. Reuse concurrent batches.
                for _ in range(16):
                    sessions.extend(
                        await asyncio.gather(
                            *(initialized_client(client, path, token) for _ in range(8))
                        )
                    )
                self.assertEqual(len({h["Mcp-Session-Id"] for h in sessions}), 128)
                response = await client.post(
                    path,
                    headers={
                        "Authorization": "Bearer " + token,
                        "Accept": "application/json, text/event-stream",
                        "Content-Type": "application/json",
                    },
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2025-03-26",
                            "capabilities": {},
                            "clientInfo": {"name": "capacity-fixture", "version": "1"},
                        },
                    },
                )
                self.assertEqual(response.status_code, 503)
                other = await initialized_client(client, endpoint, token)
                self.assertEqual((await client.delete(endpoint, headers=other)).status_code, 200)
                self.assertEqual(
                    (await client.delete(path, headers=sessions.pop())).status_code, 200
                )
                sessions.append(await initialized_client(client, path, token))
                for offset in range(0, len(sessions), 8):
                    results = await asyncio.gather(
                        *(client.delete(path, headers=h) for h in sessions[offset : offset + 8])
                    )
                    self.assertTrue(all(result.status_code == 200 for result in results))


if __name__ == "__main__":
    unittest.main()
