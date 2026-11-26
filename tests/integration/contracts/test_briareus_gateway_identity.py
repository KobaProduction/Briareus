"""Native loopback Gateway -> API -> Gateway -> external identity contract."""

from __future__ import annotations

import asyncio
import socket
import threading
import time
import unittest
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Literal

import httpx
import uvicorn
from briareus_oidc import OidcTokenVerifier, TokenAccessDenied, TokenVerificationError
from briareus_oidc.gateway_contract import (
    INTERNAL_HOST,
    METADATA_PATH,
    VERIFY_PATH,
    GatewayIdentityUnavailable,
    GatewayMetadata,
    PrincipalMessage,
)
from control_panel_api.application.identity import PanelTokenIdentity
from control_panel_api.infrastructure.gateway_identity import GatewayIdentityClient
from control_panel_api.presentation.bearer_middleware import PanelBearerMiddleware
from control_panel_api.presentation.identity import (
    build_identity_router,
    require_mutation,
    websocket_principal,
)
from fastapi import FastAPI, Request
from gateway.gateway_settings import GatewayAuthSettings
from gateway.identity_routes import GatewayIdentityRoutes
from gateway.reverse_proxy import ReverseProxy
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient
from starlette.websockets import WebSocket, WebSocketDisconnect
from zitadel_test_support import ZitadelTokenFixture

SERVICE_TOKEN = "synthetic-private-service"
PUBLIC_ORIGIN = "https://gateway.example.test"
PUBLIC_HOST = "gateway.example.test"


def listener() -> socket.socket:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(32)
    return sock


def origin(sock: socket.socket) -> str:
    return f"http://127.0.0.1:{sock.getsockname()[1]}"


@contextmanager
def serve(app: Starlette, sock: socket.socket) -> Iterator[None]:
    server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        if not server.started:
            raise RuntimeError("Local identity fixture did not start")
        yield
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
        if thread.is_alive():
            raise RuntimeError("Local identity fixture did not stop")


class GatewayIdentityContracts(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = ZitadelTokenFixture()
        self.addCleanup(self.provider.close)

    def settings(self, *, mode: Literal["jwt", "introspection"] = "jwt") -> GatewayAuthSettings:
        source = self.provider.settings
        return GatewayAuthSettings(
            issuer_url=source.issuer_url,
            audience=source.audience,
            required_role=source.required_role,
            roles_format=source.roles_format,
            roles_claim_path=source.roles_claim_path,
            roles_organization_id=source.roles_organization_id,
            public_base_url=PUBLIC_ORIGIN,
            token_verification=mode,
            client_id="resource-client",
            client_secret="synthetic-oidc-credential",
        )

    def test_real_http_roundtrip_with_no_provider_configuration_in_api(self) -> None:
        settings = self.settings()
        authority = GatewayIdentityRoutes(
            settings, OidcTokenVerifier(settings), SERVICE_TOKEN, "registered-public-client"
        )
        gateway_socket = listener()
        api_socket = listener()
        proxy = ReverseProxy(
            origin(api_socket),
            backend_name="panel",
            public_prefix="/api",
            upstream_prefix="/admin/api",
        )

        @asynccontextmanager
        async def gateway_lifespan(_app: Starlette) -> AsyncIterator[None]:
            yield
            await proxy.close()

        gateway = Starlette(
            routes=[
                *authority.routes(),
                Route("/api/{path:path}", proxy.handle, methods=["GET", "POST"]),
            ],
            lifespan=gateway_lifespan,
        )
        with serve(gateway, gateway_socket):
            remote = GatewayIdentityClient(SERVICE_TOKEN, origin=origin(gateway_socket))
            metadata = remote.bootstrap()
            self.assertEqual(
                metadata, GatewayMetadata(version=1, node_id="access", public_origin=PUBLIC_ORIGIN)
            )
            identity = PanelTokenIdentity(remote, metadata.node_id)

            @asynccontextmanager
            async def api_lifespan(_app: FastAPI) -> AsyncIterator[None]:
                yield
                await remote.close()

            api = FastAPI(lifespan=api_lifespan)
            api.add_middleware(PanelBearerMiddleware, identity=identity)
            api.include_router(build_identity_router(identity))

            @api.post("/admin/api/change")
            def change(request: Request) -> dict[str, str]:
                return {
                    "subject": require_mutation(request, identity, metadata.public_origin).subject
                }

            with (
                serve(api, api_socket),
                httpx.Client(
                    base_url=origin(gateway_socket), headers={"Host": PUBLIC_HOST}, trust_env=False
                ) as caller,
            ):
                config = caller.get("/api/identity/config")
                self.assertEqual(config.status_code, 200)
                self.assertEqual(config.json()["client_id"], "registered-public-client")
                self.assertEqual(config.json()["redirect_uri"], PUBLIC_ORIGIN + "/admin/")
                self.assertIn("urn:zitadel:iam:org:projects:roles", config.json()["scope"])
                self.assertNotIn("synthetic-oidc-credential", config.text)
                self.assertEqual(caller.get(METADATA_PATH).status_code, 404)
                private = {"Host": INTERNAL_HOST, "Authorization": "Bearer " + SERVICE_TOKEN}
                self.assertEqual(caller.get(METADATA_PATH, headers=private).status_code, 200)
                self.assertEqual(
                    caller.get(METADATA_PATH, headers={"Host": INTERNAL_HOST}).status_code, 401
                )
                self.assertEqual(
                    caller.post(
                        VERIFY_PATH, headers=private, json={"token": "x", "unexpected": True}
                    ).status_code,
                    400,
                )
                self.assertEqual(caller.get("/api/identity").status_code, 401)
                self.assertEqual(
                    caller.get(
                        "/api/identity", headers={"X-Briareus-Principal": "forged"}
                    ).status_code,
                    401,
                )
                token = self.provider.token(
                    {
                        "preferred_username": "operator",
                        "name": "Verified user",
                        "private_claim": "not-forwarded",
                    }
                )
                headers = {"Authorization": "Bearer " + token}
                response = caller.get("/api/identity", headers=headers)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.json(),
                    {"authenticated": True, "username": "Verified user", "subject": "user-1"},
                )
                wire = caller.post(VERIFY_PATH, headers=private, json={"token": token})
                self.assertEqual(wire.status_code, 200)
                self.assertNotIn("private_claim", wire.text)
                self.assertNotIn(token, wire.text)
                self.assertEqual(remote.verify(token).claims, {})
                self.assertEqual(caller.post("/api/change", headers=headers).status_code, 403)
                self.assertEqual(
                    caller.post(
                        "/api/change", headers={**headers, "Origin": PUBLIC_ORIGIN}
                    ).status_code,
                    200,
                )
                for changes, expected in (
                    ({"aud": "wrong"}, 401),
                    ({"iss": "https://wrong.example"}, 401),
                    ({"exp": 1}, 401),
                    (
                        {
                            settings.roles_claim_path[0]: {
                                "other-node": {settings.roles_organization_id: "example.test"}
                            }
                        },
                        403,
                    ),
                ):
                    with self.subTest(expected=expected):
                        denied = caller.get(
                            "/api/identity",
                            headers={"Authorization": "Bearer " + self.provider.token(changes)},
                        )
                        self.assertEqual(denied.status_code, expected)
                self.assertEqual(self.provider.requests, 1)
                self.assertEqual(
                    caller.get(
                        "/api/identity", headers={"Authorization": "Bearer " + SERVICE_TOKEN}
                    ).status_code,
                    401,
                )
                # Gateway availability is authoritative, not a permissive local fallback.
                bad = GatewayIdentityClient("wrong-service-token", origin=origin(gateway_socket))
                try:
                    with self.assertRaises(GatewayIdentityUnavailable):
                        bad.bootstrap()
                finally:
                    asyncio.run(bad.close())

    def test_introspection_authority_cache_is_shared_by_internal_clients(self) -> None:
        settings = self.settings(mode="introspection")
        verifier = OidcTokenVerifier(settings)
        routes = GatewayIdentityRoutes(
            settings, verifier, SERVICE_TOKEN, "registered-public-client"
        )
        sock = listener()
        now = int(time.time())
        self.provider.introspection_payload = {
            "active": True,
            "iss": settings.issuer_url,
            "aud": settings.audience,
            "sub": "opaque-user",
            "client_id": "external-mcp",
            "iat": now - 1,
            "exp": now + 120,
            settings.roles_claim_path[0]: {
                "access": {settings.roles_organization_id: "example.test"}
            },
        }
        with serve(Starlette(routes=routes.routes()), sock):
            remote = GatewayIdentityClient(SERVICE_TOKEN, origin=origin(sock))
            try:
                remote.bootstrap()
                self.assertEqual(remote.verify("opaque-valid").subject, "opaque-user")

                async def verify_async_and_close() -> None:
                    self.assertEqual(
                        (await remote.verify_async("opaque-valid")).subject, "opaque-user"
                    )
                    await remote._async.aclose()

                asyncio.run(verify_async_and_close())
                self.assertEqual(self.provider.introspection_requests, 1)
                self.provider.introspection_payload = {"active": False}
                with self.assertRaises(TokenVerificationError):
                    remote.verify("opaque-revoked")
                self.provider.introspection_status = 503
                with self.assertRaises(GatewayIdentityUnavailable):
                    remote.verify("opaque-provider-down")
            finally:
                asyncio.run(remote.close())

    def test_api_http_and_websocket_fail_closed_when_gateway_stops(self) -> None:
        settings = self.settings()
        authority = GatewayIdentityRoutes(
            settings, OidcTokenVerifier(settings), SERVICE_TOKEN, "registered-public-client"
        )
        sock = listener()
        remote = GatewayIdentityClient(SERVICE_TOKEN, origin=origin(sock))
        token = self.provider.token()
        api = FastAPI()
        api.add_middleware(PanelBearerMiddleware, identity=PanelTokenIdentity(remote, "access"))
        identity = PanelTokenIdentity(remote, "access")
        api.include_router(build_identity_router(identity))

        @api.websocket("/identity-websocket")
        async def socket_identity(websocket: WebSocket) -> None:
            principal = await websocket_principal(websocket, identity, PUBLIC_ORIGIN)
            if principal is not None:
                await websocket.accept(subprotocol="briareus.v1")
                await websocket.send_json({"subject": principal.subject})
                await websocket.close()

        headers = {"Authorization": "Bearer " + token}
        with TestClient(api) as client:
            try:
                with serve(Starlette(routes=authority.routes()), sock):
                    remote.bootstrap()
                    self.assertEqual(
                        client.get("/admin/api/identity", headers=headers).status_code, 200
                    )
                    with client.websocket_connect(
                        "/identity-websocket",
                        headers={"Origin": PUBLIC_ORIGIN},
                        subprotocols=["briareus.v1", "bearer." + token],
                    ) as ws:
                        self.assertEqual(ws.receive_json(), {"subject": "user-1"})
                denied = client.get("/admin/api/identity", headers=headers)
                self.assertEqual(denied.status_code, 503)
                with (
                    self.assertRaises(WebSocketDisconnect) as caught,
                    client.websocket_connect(
                        "/identity-websocket",
                        headers={"Origin": PUBLIC_ORIGIN},
                        subprotocols=["briareus.v1", "bearer." + token],
                    ),
                ):
                    pass
                self.assertEqual(caught.exception.code, 1011)
            finally:
                assert client.portal is not None
                client.portal.call(remote.close)

    def test_wire_rejects_other_node_and_expired_principal(self) -> None:
        payload = PrincipalMessage(
            version=1,
            node_id="other",
            subject="user",
            username="user",
            display_name="user",
            roles=["other"],
            expires_at=int(time.time()) + 120,
            client_id="client",
            scopes=[],
        )
        with self.assertRaises(TokenAccessDenied):
            payload.principal("access")
        expired = payload.model_copy(update={"expires_at": 1})
        with self.assertRaises(TokenVerificationError):
            expired.principal("other")
