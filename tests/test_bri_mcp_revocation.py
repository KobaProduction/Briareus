from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import cast

import httpx
from bri_mcp_support import McpAuthorityHarness
from bri_support import ORIGIN
from fastapi import FastAPI
from fastmcp.server.auth import AccessToken
from mcp.server.auth.provider import TokenError
from mcp.shared.auth import OAuthClientInformationFull
from starlette.routing import Route
from test_bri_mcp_refresh import ControlledUpstreamProvider

from auth_service.token_status import LocalTokenStatus
from common.identity_provider import IdentityProviderError, ZitadelClient
from control_panel_api.oauth_host import install_mcp_oauth


class UpstreamRevocation:
    def __init__(self) -> None:
        self.calls = 0
        self.unavailable = False

    def revoke(self, _token: str) -> None:
        self.calls += 1
        if self.unavailable:
            raise IdentityProviderError("Provider temporarily unavailable")


class AuthFacade(ControlledUpstreamProvider):
    def __init__(self, directory: Path) -> None:
        super().__init__(directory)
        self.settings = self.harness.settings
        self._management = None
        self.upstream_revocation = UpstreamRevocation()
        self._identity_provider = cast(ZitadelClient, self.upstream_revocation)

    def get_routes(self, mcp_path: str | None = None) -> list[Route]:
        del mcp_path
        return []

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        if client_id not in {"test-client", "other-client", "confidential-client"}:
            return None
        return OAuthClientInformationFull(
            client_id=client_id,
            redirect_uris=["https://callback.example.test"],
            token_endpoint_auth_method="client_secret_post"
            if client_id == "confidential-client"
            else "none",
            client_secret="test-client-secret" if client_id == "confidential-client" else None,
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        status = await self.token_authority.status(token)
        if not status.active:
            return None
        return AccessToken(
            token=token,
            client_id=status.client_id or "",
            scopes=(status.scope or "").split(),
            expires_at=status.exp,
            resource=status.aud,
        )


class McpFamilyRevocationContracts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.provider = AuthFacade(Path(self.directory.name))
        self.family = await self.provider.harness.issue()
        client = await self.provider.get_client("test-client")
        assert client is not None
        self.client = client
        api = FastAPI()

        @api.get("/health")
        def health() -> dict[str, str]:
            return {"owner": "control-panel-api"}

        @api.get("/admin/api/session")
        def panel_session() -> dict[str, bool]:
            return {"authenticated": False}

        install_mcp_oauth(api, self.provider)
        self.http = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api),
            base_url="https://oauth.internal",
        )

    async def asyncTearDown(self) -> None:
        await self.http.aclose()

    async def status(self, token: str) -> LocalTokenStatus:
        return await self.provider.token_authority.status(token)

    async def test_oauth_coexists_with_panel_routes_and_api_owns_health(self) -> None:
        health = await self.http.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json(), {"owner": "control-panel-api"})
        session = await self.http.get("/admin/api/session")
        self.assertEqual(session.status_code, 200)
        self.assertEqual(session.json(), {"authenticated": False})
        denied = await self.http.post("/introspect", data={"token": self.family.access})
        self.assertEqual(denied.status_code, 401)

    async def test_public_client_can_revoke_without_a_client_secret_field(self) -> None:
        response = await self.http.post(
            "/revoke",
            data={
                "token": self.family.refresh,
                "client_id": "test-client",
                "token_type_hint": "refresh_token",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse((await self.status(self.family.access)).active)
        self.assertFalse(
            await self.provider.token_authority.refresh_allowed(self.family.refresh, "test-client")
        )

    async def test_unknown_token_type_hint_falls_back_to_supported_token_types(self) -> None:
        for token_use in ("access", "refresh"):
            with self.subTest(token_use=token_use):
                family = await self.provider.harness.issue(upstream_id="hint-" + token_use)
                self.assertTrue((await self.status(family.access)).active)
                response = await self.http.post(
                    "/revoke",
                    data={
                        "token": family.access if token_use == "access" else family.refresh,
                        "client_id": family.client_id,
                        "token_type_hint": "extension-token-type",
                    },
                )
                self.assertEqual(response.status_code, 200)
                self.assertFalse((await self.status(family.access)).active)
                self.assertFalse(
                    await self.provider.token_authority.refresh_allowed(
                        family.refresh, family.client_id
                    )
                )

    async def test_signed_client_cannot_claim_another_clients_durable_token_family(self) -> None:
        harness = self.provider.harness
        issuer = harness.issuer(self.family.resource)
        access_claims = issuer.verify_token(self.family.access, expected_token_use="access")
        refresh_claims = issuer.verify_token(self.family.refresh, expected_token_use="refresh")
        self.assertTrue((await self.status(self.family.access)).active)
        self.assertTrue(
            await self.provider.token_authority.refresh_allowed(self.family.refresh, "test-client")
        )
        other = await harness.issue(client_id="other-client", upstream_id="independent-client")
        mismatched_access = issuer.issue_access_token(
            client_id="other-client",
            scopes=["openid"],
            jti=access_claims["jti"],
            expires_in=300,
            upstream_claims=access_claims["upstream_claims"],
        )
        mismatched_refresh = issuer.issue_refresh_token(
            client_id="other-client",
            scopes=["openid"],
            jti=refresh_claims["jti"],
            expires_in=300,
            upstream_claims=refresh_claims["upstream_claims"],
        )
        self.assertFalse((await self.status(mismatched_access)).active)
        self.assertFalse(
            await self.provider.token_authority.refresh_allowed(mismatched_refresh, "other-client")
        )
        response = await self.http.post(
            "/revoke", data={"token": mismatched_access, "client_id": "other-client"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue((await self.status(self.family.access)).active)
        self.assertTrue((await self.status(other.access)).active)

    async def test_revoking_access_revokes_its_family_but_not_other_clients_resources_or_families(
        self,
    ) -> None:
        others = [
            await self.provider.harness.issue(
                client_id="other-client", upstream_id="other-client-family"
            ),
            await self.provider.harness.issue(
                resource=ORIGIN + "/web/mcp", upstream_id="other-resource-family"
            ),
            await self.provider.harness.issue(upstream_id="other-family"),
        ]
        response = await self.http.post(
            "/revoke",
            data={
                "token": self.family.access,
                "client_id": "test-client",
                "token_type_hint": "access_token",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse((await self.status(self.family.access)).active)
        for other in others:
            with self.subTest(
                client=other.client_id, resource=other.resource, family=other.upstream_id
            ):
                self.assertTrue((await self.status(other.access)).active)

    async def test_wrong_client_and_unknown_token_do_not_revoke_another_grant(self) -> None:
        for body in (
            {"token": self.family.access, "client_id": "other-client"},
            {"token": "unknown-token", "client_id": "test-client"},
        ):
            self.assertEqual((await self.http.post("/revoke", data=body)).status_code, 200)
        self.assertTrue((await self.status(self.family.access)).active)
        body = {"token": self.family.access, "client_id": "test-client"}
        self.assertEqual((await self.http.post("/revoke", data=body)).status_code, 200)
        self.assertEqual((await self.http.post("/revoke", data=body)).status_code, 200)
        self.assertFalse((await self.status(self.family.access)).active)

    async def test_confidential_client_authentication_is_not_downgraded_to_public(self) -> None:
        family = await self.provider.harness.issue(
            client_id="confidential-client", upstream_id="confidential-family"
        )
        body = {"token": family.access, "client_id": "confidential-client"}
        self.assertEqual((await self.http.post("/revoke", data=body)).status_code, 401)
        self.assertTrue((await self.status(family.access)).active)
        body["client_secret"] = "test-client-secret"
        self.assertEqual((await self.http.post("/revoke", data=body)).status_code, 200)
        self.assertFalse((await self.status(family.access)).active)

    async def test_local_revocation_survives_provider_outage_and_auth_process_restart(self) -> None:
        self.provider.upstream_revocation.unavailable = True
        response = await self.http.post(
            "/revoke",
            data={
                "token": self.family.refresh,
                "client_id": "test-client",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse((await self.status(self.family.access)).active)
        restarted = McpAuthorityHarness(Path(self.directory.name))
        self.assertFalse((await restarted.authority.status(self.family.access)).active)
        self.assertFalse(
            await restarted.authority.refresh_allowed(self.family.refresh, "test-client")
        )

    async def test_cached_refresh_replay_cannot_resurrect_a_revoked_family(self) -> None:
        refresh = await self.provider.load_refresh_token(self.client, self.family.refresh)
        assert refresh is not None
        first = await self.provider.exchange_refresh_token(self.client, refresh, ["openid"])
        loaded_old = await self.provider.load_refresh_token(self.client, self.family.refresh)
        assert loaded_old is not None
        replay = await self.provider.exchange_refresh_token(self.client, loaded_old, ["openid"])
        self.assertEqual(first, replay)
        response = await self.http.post(
            "/revoke",
            data={
                "token": first.refresh_token or "",
                "client_id": "test-client",
                "token_type_hint": "refresh_token",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse((await self.status(self.family.access)).active)
        self.assertFalse((await self.status(first.access_token)).active)
        self.assertFalse(
            await self.provider.token_authority.refresh_allowed(
                first.refresh_token or "", "test-client"
            )
        )
        self.assertIsNone(await self.provider.load_refresh_token(self.client, self.family.refresh))
        with self.assertRaises(TokenError):
            await self.provider.exchange_refresh_token(self.client, refresh, ["openid"])

    async def test_private_introspection_requires_its_service_credential_and_never_returns_secrets(
        self,
    ) -> None:
        body = {"token": self.family.access}
        self.assertEqual((await self.http.post("/introspect", data=body)).status_code, 401)
        response = await self.http.post(
            "/introspect",
            data=body,
            headers={
                "Authorization": "Bearer " + self.provider.settings.resolved_introspection_token
            },
        )
        self.assertEqual(response.status_code, 200)
        status = LocalTokenStatus.model_validate(response.json())
        self.assertTrue(status.active)
        self.assertEqual(status.aud, self.family.resource)
        self.assertNotIn(self.family.access, response.text)
        self.assertNotIn(self.family.refresh, response.text)
        self.assertNotIn("test-upstream", response.text)
