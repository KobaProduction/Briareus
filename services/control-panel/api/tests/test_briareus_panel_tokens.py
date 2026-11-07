from __future__ import annotations

import json
import unittest
from dataclasses import replace
from unittest.mock import AsyncMock, Mock, patch

from briareus_support import ORIGIN, SUBJECT, TokenAuthorityHarness
from control_panel_api.presentation.bearer_middleware import PanelBearerMiddleware
from control_panel_api.presentation.identity import (
    build_identity_router,
    require_mutation,
    websocket_principal,
)
from fastapi import FastAPI, Request
from starlette.testclient import TestClient
from starlette.websockets import WebSocket, WebSocketDisconnect


class PanelTokenContracts(unittest.TestCase):
    def setUp(self) -> None:
        self.authority = TokenAuthorityHarness()
        self.addCleanup(self.authority.close)
        self.app = FastAPI()
        self.app.add_middleware(PanelBearerMiddleware, identity=self.authority.identity)
        self.app.include_router(build_identity_router(self.authority.identity, ORIGIN))

        @self.app.post("/admin/api/change")
        def change(request: Request) -> dict[str, str]:
            principal = require_mutation(request, self.authority.identity, ORIGIN)
            return {"subject": principal.subject}

        @self.app.websocket("/socket")
        async def socket(websocket: WebSocket) -> None:
            principal = await websocket_principal(websocket, self.authority.identity, ORIGIN)
            if principal is not None:
                await websocket.accept(subprotocol="briareus.v1")
                await websocket.send_json({"subject": principal.subject})
                await websocket.close()

    def test_public_configuration_uses_configured_provider_scopes(self) -> None:
        with TestClient(self.app) as client:
            response = client.get("/admin/api/identity/config")
        self.assertEqual(response.status_code, 200)
        config = response.json()
        self.assertEqual(config["issuer"], self.authority.settings.issuer_url)
        self.assertEqual(config["scope"], " ".join(self.authority.settings.authorization_scopes))
        self.assertNotIn("zitadel", config["scope"])

    def test_panel_client_cannot_be_used_as_api_audience(self) -> None:
        with self.assertRaises(ValueError):
            replace(self.authority.identity, audience=self.authority.identity.oidc.client_id)

    def test_cookie_alone_never_authenticates_and_bearer_uses_cached_jwks(self) -> None:
        token = self.authority.authenticate()
        with (
            patch.object(
                self.authority.verifier.jwks, "fetch_data", side_effect=AssertionError("network")
            ),
            TestClient(self.app) as client,
        ):
            client.cookies.set("session", "retired-session-cookie")
            self.assertEqual(client.get("/admin/api/identity").status_code, 401)
            for _ in range(3):
                response = client.get(
                    "/admin/api/identity", headers={"Authorization": f"Bearer {token}"}
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["subject"], SUBJECT)
                self.assertNotIn("set-cookie", response.headers)

    def test_mutation_needs_bearer_and_exact_origin_without_owned_csrf(self) -> None:
        headers = {"Authorization": f"Bearer {self.authority.authenticate()}"}
        with TestClient(self.app) as client:
            self.assertEqual(client.post("/admin/api/change", headers=headers).status_code, 403)
            response = client.post("/admin/api/change", headers={**headers, "Origin": ORIGIN})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"subject": SUBJECT})

    def test_panel_rejects_expired_token_or_absent_project_access_grant(self) -> None:
        tokens = [
            (self.authority.authenticate(lifetime=-1), 401),
            (self.authority.authenticate(role="mcp"), 403),
        ]
        with TestClient(self.app) as client:
            for token, status in tokens:
                with self.subTest(status=status):
                    response = client.get(
                        "/admin/api/identity", headers={"Authorization": f"Bearer {token}"}
                    )
                    self.assertEqual(response.status_code, status)
                    self.assertNotIn(token, response.text)
                    if status == 403:
                        self.assertEqual(response.json(), {"detail": {"code": "access_denied"}})

    def test_websocket_accepts_protocol_bearer_but_echoes_only_public_protocol(self) -> None:
        token = self.authority.authenticate()
        with (
            TestClient(self.app) as client,
            client.websocket_connect(
                "/socket",
                headers={"Origin": ORIGIN},
                subprotocols=["briareus.v1", "bearer." + token],
            ) as socket,
        ):
            self.assertEqual(socket.accepted_subprotocol, "briareus.v1")
            self.assertEqual(socket.receive_json(), {"subject": SUBJECT})

    def test_panel_requires_this_node_grant_instead_of_global_or_other_node_access(self) -> None:
        self.authority.verifier.settings = self.authority.settings.model_copy(
            update={"required_role": "tambov"}
        )
        with TestClient(self.app) as client:
            for role, expected in (("access", 403), ("moscow", 403), ("tambov", 200)):
                with self.subTest(role=role):
                    response = client.get("/admin/api/identity", headers={
                        "Authorization": "Bearer " + self.authority.authenticate(role=role),
                    })
                    self.assertEqual(response.status_code, expected)

    def test_websocket_rejects_missing_token_and_wrong_origin(self) -> None:
        token = self.authority.authenticate()
        examples = [
            (ORIGIN, ["briareus.v1"], 4401),
            (ORIGIN, ["briareus.v1", "bearer." + self.authority.authenticate(role="mcp")], 4403),
            ("https://other.example.test", ["briareus.v1", "bearer." + token], 4403),
        ]
        with TestClient(self.app) as client:
            for origin, protocols, code in examples:
                with (
                    self.subTest(origin=origin),
                    self.assertRaises(WebSocketDisconnect) as error,
                    client.websocket_connect(
                        "/socket", headers={"Origin": origin}, subprotocols=protocols
                    ),
                ):
                    self.fail("Unauthorized socket admitted")
                self.assertEqual(error.exception.code, code)


class PanelEventStreamExpiryContracts(unittest.IsolatedAsyncioTestCase):
    async def test_expiry_during_snapshot_fetch_prevents_sse_payload(self) -> None:
        from control_panel_api.application.services import InvocationAuditService
        from control_panel_api.domain.telemetry import Invocation
        from control_panel_api.presentation.admin_routes.calls import CallsRoutes
        from control_panel_api.presentation.admin_routes.context import WebApiContext

        authority = TokenAuthorityHarness()
        self.addCleanup(authority.close)
        principal = authority.identity.verify(authority.authenticate())
        audit = Mock(spec=InvocationAuditService)
        event = Invocation(module="server", tool="read", status="success", duration_ms=1)

        def snapshot(*, limit: int) -> list[Invocation]:
            self.assertEqual(limit, 100)
            authority.expire()
            return [event]

        audit.recent.side_effect = snapshot
        routes = CallsRoutes(Mock(spec=WebApiContext))
        request = Request({"type": "http", "headers": []})
        stream = routes.call_events(request, audit, principal)
        with self.assertRaises(StopAsyncIteration):
            await anext(stream)
        audit.recent.assert_called_once_with(limit=100)

    async def test_event_and_keepalive_frames_use_real_sse_line_boundaries(self) -> None:
        from control_panel_api.application.services import InvocationAuditService
        from control_panel_api.domain.telemetry import Invocation
        from control_panel_api.presentation.admin_routes.calls import CallsRoutes
        from control_panel_api.presentation.admin_routes.context import WebApiContext

        authority = TokenAuthorityHarness()
        self.addCleanup(authority.close)
        principal = authority.identity.verify(authority.authenticate())
        event = Invocation(module="server", tool="read", status="success", duration_ms=1)
        routes = CallsRoutes(Mock(spec=WebApiContext))
        frames = list(routes.event_lines([event], set(), principal))
        self.assertEqual(len(frames), 1)
        self.assertTrue(frames[0].startswith("data: "))
        self.assertTrue(frames[0].endswith("\n\n"))
        self.assertEqual(frames[0].count("\n"), 2)
        self.assertEqual(json.loads(frames[0][6:-2])["id"], event.id)
        audit = Mock(spec=InvocationAuditService)
        audit.recent.return_value = []
        request = Mock(spec=Request)
        request.is_disconnected = AsyncMock(return_value=False)
        stream = routes.call_events(request, audit, principal)
        self.assertEqual(await anext(stream), ": keepalive\n\n")
        await stream.aclose()
