from __future__ import annotations

import asyncio
import unittest

import httpx
from briareus_support import ORIGIN, SUBJECT, TokenAuthorityHarness
from control_panel_api.presentation.bearer_middleware import PanelBearerMiddleware
from control_panel_api.presentation.identity import build_identity_router
from fastapi import FastAPI
from gateway.reverse_proxy import ReverseProxy
from starlette.applications import Starlette
from starlette.routing import Route


class PublicGatewayBearerIsolationContracts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.authority = TokenAuthorityHarness()
        backend = FastAPI()
        backend.add_middleware(PanelBearerMiddleware, identity=self.authority.identity)
        backend.include_router(build_identity_router(self.authority.identity, ORIGIN))
        self.proxy = ReverseProxy(
            "http://control-panel-api:8000",
            backend_name="control-panel-api",
            public_prefix="/api",
            upstream_prefix="/admin/api",
        )
        await self.proxy._client.aclose()
        self.proxy._client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=backend),
            follow_redirects=False,
        )
        gateway = Starlette(routes=[Route("/api/{path:path}", self.proxy.handle, methods=["GET"])])
        self.human = httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway), base_url=ORIGIN)
        self.anonymous = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=gateway), base_url=ORIGIN
        )
        self.token = self.authority.authenticate()

    async def asyncTearDown(self) -> None:
        await self.human.aclose()
        await self.anonymous.aclose()
        await self.proxy.close()
        self.authority.close()

    async def test_authenticated_request_never_authorizes_later_anonymous_client(self) -> None:
        authenticated = await self.human.get(
            "/api/identity", headers={"Authorization": f"Bearer {self.token}"}
        )
        self.assertEqual(authenticated.status_code, 200)
        self.assertEqual(authenticated.json()["subject"], SUBJECT)
        self.assertNotIn("set-cookie", authenticated.headers)
        self.assertEqual((await self.anonymous.get("/api/identity")).status_code, 401)
        self.assertEqual((await self.human.get("/api/identity")).status_code, 401)

    async def test_concurrent_browsers_cannot_use_internal_service_token_for_panel(self) -> None:
        for _ in range(3):
            human, machine = await asyncio.gather(
                self.human.get("/api/identity", headers={"Authorization": f"Bearer {self.token}"}),
                self.anonymous.get(
                    "/api/identity", headers={"Authorization": "Bearer internal-service-token"}
                ),
            )
            self.assertEqual(human.status_code, 200)
            self.assertEqual(machine.status_code, 401)

    async def test_public_oidc_config_has_no_secret_and_old_auth_routes_are_absent(self) -> None:
        response = await self.anonymous.get("/api/identity/config")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["client_id"], "public-spa")
        self.assertNotIn("secret", str(response.json()))
        for path in ("/api/auth/login", "/api/auth/callback", "/api/logout", "/api/session"):
            self.assertEqual((await self.anonymous.get(path)).status_code, 404)
