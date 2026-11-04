from __future__ import annotations

import time
import unittest
from dataclasses import dataclass
from typing import cast
from unittest.mock import patch

import httpx
import jwt
from briareus_identity.identity_provider import (
    IdentityProviderError,
    ProviderIdentity,
    ZitadelClient,
)
from briareus_identity.identity_settings import ZitadelSettings, identity_origin
from briareus_support import ISSUER, SUBJECT
from cryptography.hazmat.primitives.asymmetric import rsa

_HTTP_CLIENT = httpx.Client


@dataclass(frozen=True)
class SigningKey:
    key: rsa.RSAPublicKey


class KeyResolver:
    def __init__(self, key: rsa.RSAPublicKey) -> None:
        self.key = key

    def get_signing_key_from_jwt(self, _token: str) -> SigningKey:
        return SigningKey(self.key)


class IdentityProviderContracts(unittest.TestCase):
    def test_username_alias_fallback_preserves_preferred_username_precedence(self) -> None:
        examples = (
            ({"username": "legacy"}, "legacy"),
            ({"preferred_username": "preferred", "username": "legacy"}, "preferred"),
            ({"preferred_username": "", "username": "legacy"}, ""),
            ({}, ""),
        )
        for claims, expected in examples:
            with self.subTest(claims=claims):
                identity = ProviderIdentity.model_validate({"sub": SUBJECT, **claims})
                self.assertEqual(identity.preferred_username, expected)

    def setUp(self) -> None:
        self.metadata: dict[str, object] = {
            "issuer": ISSUER,
            **{
                name: ISSUER + "/" + name
                for name in (
                    "authorization_endpoint",
                    "token_endpoint",
                    "userinfo_endpoint",
                    "jwks_uri",
                    "introspection_endpoint",
                    "revocation_endpoint",
                    "end_session_endpoint",
                )
            },
        }
        self.introspection: dict[str, object] = {"active": False}
        self.http_status = 200
        self.requests: list[httpx.Request] = []
        self.transport = httpx.MockTransport(self.response)
        self.settings = ZitadelSettings(
            issuer_url=ISSUER,
            client_id="briareus-client",
            client_secret="test-client-secret",
            allowed_subjects=(SUBJECT,),
        )
        self.provider = ZitadelClient(self.settings)
        self.client_patch = patch(
            "briareus_identity.identity_provider.httpx.Client",
            side_effect=self.client,
        )
        self.client_patch.start()
        self.addCleanup(self.client_patch.stop)

    def client(self, *_args: object, **_kwargs: object) -> httpx.Client:
        return _HTTP_CLIENT(transport=self.transport)

    def response(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        document = (
            self.introspection
            if request.url.path.endswith("introspection_endpoint")
            else self.metadata
        )
        return httpx.Response(self.http_status, json=document)

    def test_http_development_origins_allow_only_loopback_and_reserved_localhost_names(
        self,
    ) -> None:
        for origin in (
            "http://localhost:18081",
            "http://127.0.0.1:18081",
            "http://identity.previous.localhost:18081",
        ):
            with self.subTest(origin=origin):
                self.assertEqual(identity_origin(origin, allow_local_http=True), origin)
                with self.assertRaises(ValueError):
                    identity_origin(origin, allow_local_http=False)
        for origin in (
            "http://identity.example.test",
            "http://localhost.attacker.test",
            "http://10.0.0.4",
        ):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                identity_origin(origin, allow_local_http=True)

    def test_discovery_requires_exact_issuer_and_same_origin_endpoints(self) -> None:
        for change in (
            {"issuer": "https://untrusted.example.test"},
            {"token_endpoint": "https://untrusted.example.test/token"},
            {"jwks_uri": "http://identity.example.test/keys"},
        ):
            with self.subTest(change=change):
                self.metadata.update(change)
                with self.assertRaises(IdentityProviderError):
                    self.provider.metadata()
                for key in change:
                    self.metadata[key] = ISSUER if key == "issuer" else ISSUER + "/" + key

    def test_unavailable_discovery_does_not_become_an_authentication_fallback(self) -> None:
        self.http_status = 503
        with self.assertRaises(IdentityProviderError):
            self.provider.metadata()

    def test_http_is_only_enabled_explicitly_for_local_identity(self) -> None:
        for origin, enabled in (("http://localhost:18081", False), ("http://public.example", True)):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                identity_origin(origin, allow_local_http=enabled)
        self.assertEqual(
            identity_origin("http://auth.briareus.localhost:18081", allow_local_http=True),
            "http://auth.briareus.localhost:18081",
        )

    def test_identity_origin_rejects_credentials_paths_and_control_characters(self) -> None:
        for origin in (
            "https://user:password@identity.example.test",
            ISSUER + "/private",
            ISSUER + "?issuer=other",
            ISSUER + "\n",
            ISSUER + "#fragment",
        ):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                identity_origin(origin, allow_local_http=False)

    def test_explicit_subject_authority_is_required_at_bootstrap(self) -> None:
        for change in ({"allowed_subjects": ()}, {"client_id": ""}, {"client_secret": ""}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                ZitadelClient(self.settings.model_copy(update=change))

    def test_revoked_expired_wrong_issuer_or_subject_tokens_are_rejected(self) -> None:
        base: dict[str, object] = {
            "active": True,
            "sub": SUBJECT,
            "iss": ISSUER,
            "exp": int(time.time()) + 300,
            "client_id": "briareus-client",
            "aud": ["briareus-client"],
        }
        # These are negative protocol cases, not evidence of the live provider's audience shape.
        for changes in (
            {"active": False},
            {"exp": 0},
            {"iss": "https://other.example.test"},
            {"sub": "unappointed"},
            {"aud": ["another-client"]},
            {"client_id": ""},
        ):
            with self.subTest(changes=changes):
                self.introspection = {**base, **changes}
                with self.assertRaises(IdentityProviderError):
                    self.provider.introspect("test-access")

    def test_provider_issued_static_client_audience_is_accepted(self) -> None:
        # Shape verified against a genuine ZITADEL 4.19.4 token in the local hosted login.
        self.introspection = {
            "active": True,
            "sub": SUBJECT,
            "iss": ISSUER,
            "exp": int(time.time()) + 300,
            "client_id": "briareus-client",
            "aud": ["briareus-client", "provider-project"],
            "scope": "openid profile email offline_access",
        }
        identity = self.provider.introspect("test-access")
        self.assertEqual(identity.sub, SUBJECT)
        self.assertEqual(identity.client_id, "briareus-client")
        self.assertIn("openid", identity.scope.split())

    def test_id_token_uses_signature_audience_issuer_expiry_and_nonce(self) -> None:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.provider._keys = cast(jwt.PyJWKClient, KeyResolver(key.public_key()))
        claims: dict[str, object] = {
            "iss": ISSUER,
            "sub": SUBJECT,
            "aud": "briareus-client",
            "nonce": "expected-nonce",
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
        }
        accepted = jwt.encode(claims, key, algorithm="RS256")
        self.assertEqual(self.provider._verify_id_token(accepted, "expected-nonce").sub, SUBJECT)
        for changes in (
            {"aud": "other-client"},
            {"iss": "https://other.example.test"},
            {"exp": 1},
            {"nonce": "other-browser"},
            {"sub": "unappointed"},
        ):
            token = jwt.encode({**claims, **changes}, key, algorithm="RS256")
            with (
                self.subTest(changes=changes),
                self.assertRaises((IdentityProviderError, jwt.PyJWTError)),
            ):
                self.provider._verify_id_token(token, "expected-nonce")
        other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        with self.assertRaises(jwt.PyJWTError):
            self.provider._verify_id_token(
                jwt.encode(claims, other_key, algorithm="RS256"),
                "expected-nonce",
            )

    def test_authorize_uses_pkce_nonce_and_state_without_exposing_client_secret(self) -> None:
        url = self.provider.authorization_url(
            callback_url="https://briareus.example.test/callback",
            state="browser-state",
            nonce="browser-nonce",
            challenge="pkce-challenge",
        )
        self.assertIn("code_challenge_method=S256", url)
        self.assertIn("state=browser-state", url)
        self.assertIn("nonce=browser-nonce", url)
        self.assertNotIn("test-client-secret", url)
