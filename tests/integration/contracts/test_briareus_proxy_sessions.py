from __future__ import annotations

import asyncio
import unittest
from urllib.parse import parse_qs, urlsplit

import httpx
from briareus_support import ORIGIN, SUBJECT, IdentityHarness
from control_panel_api.presentation.identity import build_identity_router
from fastapi import FastAPI
from gateway.reverse_proxy import ReverseProxy
from starlette.applications import Starlette
from starlette.middleware.sessions import SessionMiddleware
from starlette.routing import Route


class PublicGatewaySessionIsolationContracts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.identity = IdentityHarness()
        backend = FastAPI()
        backend.add_middleware(SessionMiddleware, secret_key="test-cookie-key")
        backend.include_router(build_identity_router(self.identity.service, ORIGIN))
        self.proxy = ReverseProxy(
            "http://control-panel-api:8000",
            backend_name="control-panel-api",
            public_prefix="/api",
            upstream_prefix="/admin/api",
        )
        # Replace the wire transport and preserve the proxy's actual cookie policy.
        cookies = self.proxy._client.cookies.jar
        await self.proxy._client.aclose()
        self.proxy._client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=backend),
            cookies=cookies,
            follow_redirects=False,
        )
        gateway = Starlette(
            routes=[Route("/api/{path:path}", self.proxy.handle, methods=["GET", "POST"])]
        )
        self.human = httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway), base_url=ORIGIN)
        self.anonymous = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=gateway), base_url=ORIGIN
        )

    async def asyncTearDown(self) -> None:
        await self.human.aclose()
        await self.anonymous.aclose()
        await self.proxy.close()
        self.identity.close()

    async def login(self) -> None:
        start = await self.human.get("/api/auth/login")
        self.assertEqual(start.status_code, 303)
        state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
        response = await self.human.get(
            "/api/auth/callback", params={"state": state, "code": "code"}
        )
        self.assertEqual(response.status_code, 303)
        self.assertIn("set-cookie", response.headers)
        current = await self.human.get("/api/session")
        self.assertEqual(current.json()["subject"], SUBJECT)

    async def test_upstream_set_cookie_never_authenticates_a_later_anonymous_client(self) -> None:
        self.assertFalse((await self.anonymous.get("/api/session")).json()["authenticated"])
        await self.login()
        anonymous = await self.anonymous.get("/api/session")
        self.assertFalse(anonymous.json()["authenticated"])
        self.assertIsNone(anonymous.json()["subject"])
        self.assertEqual(anonymous.json()["csrf_token"], "")
        self.assertTrue((await self.human.get("/api/session")).json()["authenticated"])

    async def test_concurrent_browsers_and_service_headers_do_not_share_human_authority(
        self,
    ) -> None:
        await self.login()
        for _ in range(4):
            human, anonymous = await asyncio.gather(
                self.human.get("/api/session"),
                self.anonymous.get(
                    "/api/session", headers={"Authorization": "Bearer test-service-token"}
                ),
            )
            self.assertTrue(human.json()["authenticated"])
            self.assertFalse(anonymous.json()["authenticated"])

    async def test_logout_revokes_the_human_session_without_changing_another_client(self) -> None:
        await self.login()
        current = (await self.human.get("/api/session")).json()
        response = await self.human.post(
            "/api/logout",
            headers={"Origin": ORIGIN, "X-CSRF-Token": str(current["csrf_token"])},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse((await self.human.get("/api/session")).json()["authenticated"])
        self.assertFalse((await self.anonymous.get("/api/session")).json()["authenticated"])
