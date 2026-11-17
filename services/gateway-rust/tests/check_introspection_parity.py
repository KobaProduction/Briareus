"""Compare RFC7662 opaque access-token authorization with Python Gateway."""

from __future__ import annotations

import asyncio
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "shared/identity/token-verification/src"))
sys.path.insert(0, str(ROOT / "shared/python/environment-models/src"))
sys.path.insert(0, str(ROOT / "shared/python/environment-parsing/src"))
sys.path.insert(0, str(ROOT / "shared/contracts/json-values/src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from briareus_oidc import (  # noqa: E402
    OidcTokenSettings,
    OidcTokenVerifier,
    TokenVerificationError,
)
from check_oidc_parity import issuer_fixture, rust_gateway  # noqa: E402


class OpaqueTokenContract(unittest.IsolatedAsyncioTestCase):
    async def test_introspection_issuer_audience_roles_and_expiration(self) -> None:
        replies: dict[str, dict[str, object]] = {}
        async with issuer_fixture(replies) as (issuer, _):
            now = int(time.time())
            role_key = "urn:zitadel:iam:org:project:fixture-project:roles"
            for role_format, role_path, organization in (
                ("list", '["roles"]', ""),
                ("organization_grants", f'["{role_key}"]', "fixture-org"),
            ):
                valid_role: dict[str, object] = (
                    {"roles": ["tambov"]}
                    if role_format == "list"
                    else {role_key: {"tambov": {"fixture-org": "fixture-project"}}}
                )
                absent_role: dict[str, object] = (
                    {"roles": ["other-node"]}
                    if role_format == "list"
                    else {role_key: {"tambov": {"wrong-org": "fixture-project"}}}
                )
                base = {
                    "active": True,
                    "iss": issuer,
                    "aud": "fixture-project",
                    "sub": "fixture-user",
                    "client_id": "fixture-client",
                    "exp": now + 180,
                    "iat": now - 5,
                    **valid_role,
                }
                scenarios: dict[str, tuple[dict[str, object], bool]] = {
                    "valid": (base, True),
                    "wrong_audience": ({**base, "aud": "not-project"}, False),
                    "wrong_issuer": ({**base, "iss": "https://other.example"}, False),
                    "wrong_role": ({**base, **absent_role}, False),
                    "expired": ({**base, "exp": now - 5}, False),
                    "future_nbf": ({**base, "nbf": now + 60}, False),
                    "future_iat": ({**base, "iat": now + 60}, False),
                    "wrong_azp": ({**base, "azp": "another-client"}, False),
                    "no_client": ({k: v for k, v in base.items() if k != "client_id"}, False),
                    "inactive": ({"active": False}, False),
                }
                prefix = f"opaque-{role_format}-"
                replies.update({prefix + key: value for key, (value, _) in scenarios.items()})
                python = OidcTokenVerifier(
                    OidcTokenSettings(
                        token_verification="introspection",
                        issuer_url=issuer,
                        audience="fixture-project",
                        required_role="tambov",
                        roles_claim_path=("roles",) if role_format == "list" else (role_key,),
                        roles_format=role_format,
                        roles_organization_id=organization,
                        introspection_client_id="fixture client",
                        introspection_client_secret="s3cret+with space",
                    )
                )
                async with rust_gateway(
                    issuer,
                    role_format,
                    role_path,
                    organization,
                    verification_mode="introspection",
                ) as (client, endpoint):
                    for name, (_, expected) in scenarios.items():
                        token = prefix + name
                        try:
                            await asyncio.to_thread(python.verify, token)
                            python_accepted = True
                        except TokenVerificationError:
                            python_accepted = False
                        result = await client.post(
                            endpoint,
                            headers={
                                "Authorization": "Bearer " + token,
                                "Accept": "application/json, text/event-stream",
                            },
                            json={
                                "jsonrpc": "2.0",
                                "id": 1,
                                "method": "initialize",
                                "params": {
                                    "protocolVersion": "2025-03-26",
                                    "capabilities": {},
                                    "clientInfo": {"name": "fixture", "version": "1"},
                                },
                            },
                        )
                        with self.subTest(role_format=role_format, scenario=name):
                            self.assertEqual(python_accepted, expected)
                            self.assertEqual(
                                result.status_code == 200,
                                python_accepted,
                                f"status={result.status_code} payload={result.text[:120]}",
                            )
                    token = prefix + "valid"
                    cached = await client.post(
                        endpoint,
                        headers={
                            "Authorization": "Bearer " + token,
                            "Accept": "application/json, text/event-stream",
                        },
                        json={
                            "jsonrpc": "2.0",
                            "id": 3,
                            "method": "initialize",
                            "params": {
                                "protocolVersion": "2025-03-26",
                                "capabilities": {},
                                "clientInfo": {"name": "fixture", "version": "1"},
                            },
                        },
                    )
                    self.assertEqual(cached.status_code, 200)


if __name__ == "__main__":
    unittest.main()
