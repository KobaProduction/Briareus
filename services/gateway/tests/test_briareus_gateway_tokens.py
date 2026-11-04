from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

import httpx
from briareus_mcp_support import McpAuthorityHarness
from briareus_support import ISSUER, ORIGIN, SUBJECT
from fastmcp.server.auth.jwt_issuer import JWTIssuer, derive_jwt_key
from fastmcp.server.auth.oauth_proxy.models import JTIMapping
from gateway.auth_client import LocalAuthTokenVerifier
from gateway.gateway_settings import GatewayAuthSettings
from gateway.token_status import LocalTokenStatusClient
from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


class GatewayMcpTokenContracts(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.harness = McpAuthorityHarness(Path(self.directory.name))
        self.settings = GatewayAuthSettings(
            public_base_url=ORIGIN,
            identity_issuer_url=ISSUER,
            allowed_subjects=(SUBJECT,),
            oauth_jwt_signing_key=self.harness.settings.resolved_signing_key,
        )
        self.resource = ORIGIN + "/server/mcp"
        self.signing_key = derive_jwt_key(
            low_entropy_material=self.settings.resolved_signing_key,
            salt="fastmcp-jwt-signing-key",
        )
        self.status_overrides: dict[str, object] = {}
        self.status_http_code = 200

    async def asyncSetUp(self) -> None:
        self.family = await self.harness.issue(client_id="mcp-client")
        await self.harness.mappings.put(
            key="test-jti",
            value=JTIMapping(
                jti="test-jti",
                upstream_token_id=self.family.upstream_id,
                created_at=time.time(),
            ),
        )
        status_app = Starlette(routes=[Route("/introspect", self.introspect, methods=["POST"])])
        self.status = LocalTokenStatusClient("https://oauth.internal/introspect", "test-status-key")
        headers = self.status._client.headers
        await self.status._client.aclose()
        self.status._client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=status_app),
            headers=headers,
            trust_env=False,
        )
        self.verifier = LocalAuthTokenVerifier(
            self.settings, self.resource, token_status=self.status
        )
        self.assertIsNotNone(await self.verifier.verify_token(self.token()))

    async def asyncTearDown(self) -> None:
        await self.status.close()

    async def introspect(self, request: Request) -> JSONResponse:
        if request.headers.get("authorization") != "Bearer test-status-key":
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        form = await request.form()
        actual = await self.harness.authority.status(str(form.get("token", "")))
        body = actual.model_dump(exclude_none=True)
        body.update(self.status_overrides)
        return JSONResponse(body, status_code=self.status_http_code)

    def token(
        self,
        *,
        resource: str = "",
        upstream: dict[str, object] | None = None,
        scopes: tuple[str, ...] = ("openid",),
        issuer: str = ORIGIN,
        expires_in: int = 300,
    ) -> str:
        mint = JWTIssuer(
            issuer=str(AnyHttpUrl(issuer)),
            audience=resource or self.resource,
            signing_key=self.signing_key,
        )
        claims = (
            upstream
            if upstream is not None
            else {
                "identity_provider": "zitadel",
                "iss": ISSUER,
                "sub": SUBJECT,
            }
        )
        return mint.issue_access_token(
            client_id="mcp-client",
            scopes=list(scopes),
            jti="test-jti",
            expires_in=expires_in,
            upstream_claims=claims,
        )

    async def test_signed_exact_resource_token_is_admitted_without_network(self) -> None:
        result = await self.verifier.verify_token(self.token())
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.resource, self.resource)
        self.assertEqual(result.subject, SUBJECT)

    async def test_a_token_for_one_mcp_endpoint_cannot_authorize_another(self) -> None:
        for resource in (ORIGIN + "/web/mcp", ORIGIN + "/mcp", "https://other.example/server/mcp"):
            with self.subTest(resource=resource):
                self.assertIsNone(await self.verifier.verify_token(self.token(resource=resource)))

    async def test_legacy_or_unverified_upstream_claims_never_gain_access(self) -> None:
        for claims in (
            {},
            {"login": "administrator", "sub": SUBJECT},
            {"identity_provider": "github", "iss": ISSUER, "sub": SUBJECT},
            {"identity_provider": "zitadel", "iss": "https://other.example", "sub": SUBJECT},
            {"identity_provider": "zitadel", "iss": ISSUER, "sub": "unappointed"},
        ):
            with self.subTest(claims=claims):
                self.assertIsNone(await self.verifier.verify_token(self.token(upstream=claims)))

    async def test_scopes_issuer_expiry_and_signature_are_enforced(self) -> None:
        tokens = (
            self.token(scopes=()),
            self.token(issuer="https://other.example"),
            self.token(expires_in=-10),
            "not-a-jwt",
        )
        for token in tokens:
            with self.subTest(token_kind=token[:8]):
                self.assertIsNone(await self.verifier.verify_token(token))
        signed = self.token()
        head, payload, signature = signed.split(".")
        altered = signature[:10] + ("a" if signature[10] != "a" else "b") + signature[11:]
        self.assertIsNone(await self.verifier.verify_token(".".join((head, payload, altered))))

    async def test_identity_display_name_is_not_an_authority_selector(self) -> None:
        claims: dict[str, object] = {
            "identity_provider": "zitadel",
            "iss": ISSUER,
            "sub": "unappointed",
            "preferred_username": SUBJECT,
        }
        self.assertIsNone(await self.verifier.verify_token(self.token(upstream=claims)))

    async def test_revoked_family_or_unavailable_authority_never_admits_new_work(self) -> None:
        self.status_http_code = 503
        self.assertIsNone(await self.verifier.verify_token(self.token()))
        self.status_http_code = 200
        await self.harness.authority.revoke(self.family.refresh, "refresh", "mcp-client")
        self.assertIsNone(await self.verifier.verify_token(self.token()))

    async def test_introspection_cannot_replace_client_resource_subject_or_token_expiry(
        self,
    ) -> None:
        for override in (
            {"client_id": "other-client"},
            {"aud": ORIGIN + "/web/mcp"},
            {"sub": "other-subject"},
            {"iss": "https://other.example"},
            {"exp": 0},
            {"scope": "read:user"},
            {"active": "true"},
        ):
            with self.subTest(override=override):
                self.status_overrides = override
                self.assertIsNone(await self.verifier.verify_token(self.token()))
