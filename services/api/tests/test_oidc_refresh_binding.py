"""Refresh preserves the discovered issuer through all independently signed proofs."""

import unittest
from datetime import UTC, datetime
from urllib.parse import parse_qs

from control_panel_api._oidc import RauthyOidcAdapter
from control_panel_api._oidc_refresh import refresh_login
from control_panel_api.domain.oidc_identity import OidcIdentityRejected
from httpx import AsyncClient, MockTransport, Request, Response
from pydantic import SecretStr
from test_oidc_resource_binding import _CLIENT, _ISSUER, _RESOURCE, _SUBJECT, ProviderFixture


class RotatingProvider(ProviderFixture):
    def __init__(self) -> None:
        super().__init__()
        self.rotated_issuer = _ISSUER
        self.rotated_subject = _SUBJECT

    async def __call__(self, request: Request) -> Response:
        if not request.url.path.endswith("/oidc/token"):
            return await super().__call__(request)
        form = parse_qs(request.content.decode())
        assert form == {
            "grant_type": ["refresh_token"],
            "client_id": [_CLIENT],
            "refresh_token": ["original-rotating-credential"],
        }
        self.exchanges += 1
        now = int(datetime.now(UTC).timestamp())
        identity = self.sign(
            {
                "iss": self.rotated_issuer,
                "sub": self.rotated_subject,
                "aud": _CLIENT,
                "azp": _CLIENT,
                "typ": "Id",
                "iat": now,
                "exp": now + 300,
            }
        )
        self.access_bearer = self.sign(
            {
                "iss": _ISSUER,
                "sub": _SUBJECT,
                "aud": [_CLIENT, _RESOURCE],
                "azp": _CLIENT,
                "typ": "Bearer",
                "iat": now,
                "nbf": now,
                "exp": now + 300,
                "jti": "rotated-resource",
            }
        )
        renewal = self.sign(
            {
                "iss": _ISSUER,
                "uid": _SUBJECT,
                "aud": _CLIENT,
                "azp": _CLIENT,
                "typ": "Refresh",
                "resource": _RESOURCE,
                "iat": now,
                "nbf": now + 240,
                "exp": now + 3600,
            }
        )
        return Response(
            200,
            json={
                "id_token": identity,
                "access_token": self.access_bearer,
                "refresh_token": renewal,
                "token_type": "Bearer",
                "expires_in": 300,
            },
        )


class RefreshBindingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.fixture = RotatingProvider()
        self.http = AsyncClient(transport=MockTransport(self.fixture))
        self.provider = RauthyOidcAdapter(
            issuer=_ISSUER.rstrip("/"),
            client_id=_CLIENT,
            http_client=self.http,
            resource_audience=_RESOURCE,
        )

    async def asyncTearDown(self) -> None:
        await self.http.aclose()

    async def test_rotation_keeps_exact_discovery_issuer_for_resource_and_refresh(self) -> None:
        login = await refresh_login(
            self.provider,
            token=SecretStr("original-rotating-credential"),
            subject=_SUBJECT,
        )
        self.assertEqual(login.identity.issuer, _ISSUER)
        self.assertIsNotNone(login.refresh)
        self.assertIsNotNone(login.resource)
        assert login.resource is not None
        self.assertEqual(login.resource.issuer, _ISSUER)
        self.assertEqual(self.fixture.exchanges, 1)

    async def test_rotation_rejects_changed_signed_issuer(self) -> None:
        self.fixture.rotated_issuer = _ISSUER.rstrip("/")
        with self.assertRaises(OidcIdentityRejected):
            await refresh_login(
                self.provider,
                token=SecretStr("original-rotating-credential"),
                subject=_SUBJECT,
            )

    async def test_rotation_rejects_changed_subject(self) -> None:
        self.fixture.rotated_subject = "B" * 24
        with self.assertRaises(OidcIdentityRejected):
            await refresh_login(
                self.provider,
                token=SecretStr("original-rotating-credential"),
                subject=_SUBJECT,
            )
