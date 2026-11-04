from __future__ import annotations

import unittest
from collections.abc import Callable, Mapping
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from briareus_json_values import JsonObject
from briareus_zitadel_tokens import ZitadelTokenVerifier
from gateway.auth_client import ZitadelMcpTokenVerifier
from gateway.auth_surfaces import build_surface_auth
from gateway.browser_sockets import management_websocket_routes, relay_panel_websocket
from gateway.gateway_settings import GatewayAuthSettings
from starlette.applications import Starlette
from starlette.testclient import TestClient
from starlette.websockets import WebSocket, WebSocketDisconnect
from zitadel_test_support import ZitadelTokenFixture


class GatewayMcpTokenContracts(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.fixture = ZitadelTokenFixture()
        self.addCleanup(self.fixture.close)
        self.resource = "https://briareus.example/server/mcp"
        self.verifier = ZitadelMcpTokenVerifier(
            ZitadelTokenVerifier(self.fixture.settings),
            self.resource,
        )

    async def test_external_access_token_is_admitted_with_shared_project_audience(self) -> None:
        principal = await self.verifier.verify_token(self.fixture.token())
        self.assertIsNotNone(principal)
        assert principal is not None
        self.assertEqual(principal.subject, "user-1")
        self.assertEqual(principal.resource, self.resource)
        self.assertEqual(principal.client_id, "registered-public-client")

    async def test_one_project_access_grant_authorizes_all_mcp_surfaces(self) -> None:
        for surface in ("root", "github", "gitlab", "server", "web", "analysis", "observability"):
            verifier = ZitadelMcpTokenVerifier(
                self.verifier.verifier,
                f"https://briareus.example/{surface}/mcp",
            )
            with self.subTest(surface=surface):
                self.assertIsNotNone(await verifier.verify_token(self.fixture.token()))
        no_access: JsonObject = {
            self.fixture.settings.roles_claim: {
                "unrelated-role": {self.fixture.settings.organization_id: "example.test"},
            }
        }
        self.assertIsNone(await self.verifier.verify_token(self.fixture.token(no_access)))

    async def test_local_issuer_wrappers_and_unverified_tokens_are_rejected(self) -> None:
        for token in (
            "not-a-jwt",
            self.fixture.token({"iss": "https://briareus.example"}),
            self.fixture.token({"aud": self.resource}),
            self.fixture.token(omit=("jti", "nbf")),
        ):
            with self.subTest(kind=token[:5]):
                self.assertIsNone(await self.verifier.verify_token(token))


class GatewayAuthorityMetadataContracts(unittest.IsolatedAsyncioTestCase):
    async def test_resource_discovery_advertises_external_issuer_and_required_project_scopes(
        self,
    ) -> None:
        fixture = ZitadelTokenFixture()
        self.addCleanup(fixture.close)
        settings = GatewayAuthSettings(
            issuer_url=fixture.settings.issuer_url,
            project_id=fixture.settings.project_id,
            organization_id=fixture.settings.organization_id,
            public_base_url="https://briareus.example",
        )
        providers = build_surface_auth(settings)
        self.assertEqual(providers["server"].challenge_scopes, list(settings.authorization_scopes))
        routes = providers["server"].get_well_known_routes(mcp_path="/mcp")
        app = Starlette(routes=routes)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="https://briareus.example"
        ) as client:
            response = await client.get("/.well-known/oauth-protected-resource/server/mcp")
        self.assertEqual(response.status_code, 200)
        metadata = response.json()
        self.assertEqual(metadata["authorization_servers"], [fixture.settings.issuer_url])
        self.assertEqual(metadata["resource"], "https://briareus.example/server/mcp")
        self.assertIn(settings.audience_scope, metadata["scopes_supported"])
        self.assertIn("urn:zitadel:iam:org:projects:roles", metadata["scopes_supported"])


class GatewayBrowserBearerContracts(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.fixture = ZitadelTokenFixture()
        self.addCleanup(self.fixture.close)
        self.verifier = ZitadelTokenVerifier(self.fixture.settings)
        self.socket = MagicMock(spec=WebSocket)
        self.socket.close = AsyncMock()
        self.socket.headers = {
            "origin": "https://briareus.example",
            "cookie": "old-session=private",
        }

    async def test_bearer_is_forwarded_as_authorization_and_never_as_selected_protocol_or_cookie(
        self,
    ) -> None:
        token = self.fixture.token()
        self.socket.scope = {"subprotocols": ["briareus.v1", "bearer." + token]}
        with patch("gateway.browser_sockets.relay_websocket", new_callable=AsyncMock) as relay:
            await relay_panel_websocket(
                cast(WebSocket, self.socket),
                "/admin/api/realtime",
                verifier=self.verifier,
                public_base_url="https://briareus.example",
                backend_base_url="http://control-panel-api:8000",
            )
        assert relay.await_args is not None
        kwargs = relay.await_args.kwargs
        self.assertEqual(kwargs["subprotocol"], "briareus.v1")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer " + token)
        self.assertNotIn("Cookie", kwargs["headers"])
        self.assertTrue(kwargs["is_active"]())
        with patch("briareus_zitadel_tokens.verifier.time.time", return_value=10**12):
            self.assertFalse(kwargs["is_active"]())

    async def test_ambiguous_credentials_and_cross_origin_browser_are_denied_before_relay(
        self,
    ) -> None:
        token = self.fixture.token()
        self.socket.scope = {"subprotocols": ["briareus.v1", "bearer." + token, "bearer.another"]}
        with patch("gateway.browser_sockets.relay_websocket", new_callable=AsyncMock) as relay:
            await self._relay()
            self.socket.close.assert_awaited_with(code=4401)
            self.socket.scope = {"subprotocols": ["briareus.v1", "bearer." + token]}
            self.socket.headers["origin"] = "https://attacker.example"
            await self._relay()
            self.socket.close.assert_awaited_with(code=4403)
            relay.assert_not_awaited()
        self.assertEqual(self.fixture.requests, 0)

    async def _relay(self) -> None:
        await relay_panel_websocket(
            cast(WebSocket, self.socket),
            "/admin/api/realtime",
            verifier=self.verifier,
            public_base_url="https://briareus.example",
            backend_base_url="http://control-panel-api:8000",
        )


class GatewayCdpRouteContracts(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = ZitadelTokenFixture()
        self.addCleanup(self.fixture.close)
        self.verifier = ZitadelTokenVerifier(self.fixture.settings)

        async def relay(websocket: WebSocket, path: str) -> None:
            await relay_panel_websocket(
                websocket,
                path,
                verifier=self.verifier,
                public_base_url="https://briareus.example",
                backend_base_url="http://control-panel-api:8000",
            )

        self.app = Starlette(routes=management_websocket_routes(relay))

    def test_actual_cdp_route_relays_authenticated_target_with_stable_subprotocol(self) -> None:
        token = self.fixture.token()
        seen: list[tuple[str, str]] = []

        async def upstream(
            websocket: WebSocket,
            target_url: str,
            *,
            headers: Mapping[str, str],
            origin: str | None,
            subprotocol: str,
            is_active: Callable[[], bool],
        ) -> None:
            self.assertEqual(origin, "https://briareus.example")
            self.assertTrue(is_active())
            seen.append((target_url, headers["Authorization"]))
            await websocket.accept(subprotocol=subprotocol)
            await websocket.send_text("connected")
            await websocket.close()

        with (
            patch("gateway.browser_sockets.relay_websocket", side_effect=upstream),
            TestClient(self.app) as client,
            client.websocket_connect(
                "/api/browser/cdp/page/tab-123",
                headers={"origin": "https://briareus.example"},
                subprotocols=["briareus.v1", "bearer." + token],
            ) as socket,
        ):
            self.assertEqual(socket.accepted_subprotocol, "briareus.v1")
            self.assertEqual(socket.receive_text(), "connected")
        self.assertEqual(
            seen,
            [("ws://control-panel-api:8000/admin/api/browser/cdp/page/tab-123", "Bearer " + token)],
        )

    def test_actual_cdp_route_rejects_missing_bearer_and_cross_origin(self) -> None:
        token = self.fixture.token()
        cases = (
            (["briareus.v1"], "https://briareus.example", 4401),
            (["briareus.v1", "bearer." + token], "https://attacker.example", 4403),
        )
        with (
            patch("gateway.browser_sockets.relay_websocket", new_callable=AsyncMock) as relay,
            TestClient(self.app) as client,
        ):
            for protocols, origin, code in cases:
                with (
                    self.subTest(code=code),
                    self.assertRaises(WebSocketDisconnect) as raised,
                    client.websocket_connect(
                        "/api/browser/cdp/page/tab-123",
                        headers={"origin": origin},
                        subprotocols=protocols,
                    ),
                ):
                    self.fail("Unauthorized CDP WebSocket was accepted")
                self.assertEqual(raised.exception.code, code)
            relay.assert_not_awaited()
        self.assertEqual(self.fixture.requests, 0)
