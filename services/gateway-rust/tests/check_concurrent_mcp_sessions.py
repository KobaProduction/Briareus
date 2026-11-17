"""Bounded parallel MCP session isolation against a synthetic local Hand.

No Docker, actual provider tokens, public Gateway or production network.
"""

from __future__ import annotations

import asyncio
import sys
import time
import unittest
from pathlib import Path

import jwt

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_mcp_parity import provider_fixture, rpc  # noqa: E402
from check_oidc_parity import issuer_fixture, rust_gateway  # noqa: E402
from check_python_mcp_parity import initialized_client  # noqa: E402


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
            now = int(time.time())
            bearer = jwt.encode(
                {
                    "iss": issuer,
                    "aud": "fixture-project",
                    "sub": "synthetic-user",
                    "client_id": "synthetic-client",
                    "iat": now - 10,
                    "exp": now + 240,
                    "roles": ["tambov"],
                },
                signing_key,
                algorithm="RS256",
                headers={"kid": "fixture-key-1"},
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


if __name__ == "__main__":
    unittest.main()
