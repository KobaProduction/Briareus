from __future__ import annotations

import base64
import time
import unittest
from unittest.mock import patch

from briareus_json_values import JsonObject
from briareus_oidc import OidcTokenVerifier, TokenVerificationError
from pydantic import SecretStr
from zitadel_test_support import ZitadelTokenFixture


class IntrospectionContracts(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = ZitadelTokenFixture()
        self.addCleanup(self.fixture.close)
        self.settings = self.fixture.settings.model_copy(
            update={
                "token_verification": "introspection",
                "introspection_client_id": "resource:api",
                "introspection_client_secret": SecretStr("resource secret"),
            }
        )
        self.payload: JsonObject = {
            "active": True,
            "iss": self.settings.issuer_url,
            "aud": [self.settings.audience],
            "sub": "user-1",
            "client_id": "dynamic-client",
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()) - 1,
            "username": "arthur",
            "scope": "openid profile",
            self.settings.roles_claim_path[0]: {
                "access": {self.settings.roles_organization_id: "example.test"},
            },
        }
        self.fixture.introspection_payload = self.payload

    def test_opaque_token_is_authorized_by_provider_and_cached_without_storing_token(self) -> None:
        verifier = OidcTokenVerifier(self.settings)
        principal = verifier.verify("opaque-test-token")
        self.assertEqual(principal.username, "arthur")
        self.assertEqual(principal.client_id, "dynamic-client")
        self.assertEqual(principal.roles, ("access",))
        self.assertEqual(verifier.verify("opaque-test-token"), principal)
        self.assertEqual(self.fixture.introspection_requests, 1)
        expected = base64.b64encode(b"resource%3Aapi:resource+secret").decode()
        self.assertEqual(self.fixture.introspection_authorization, "Basic " + expected)
        self.assertNotIn("opaque-test-token", repr(verifier._cache))
        self.assertNotIn("resource secret", repr(self.settings))

    def test_inactive_revoked_expired_and_wrong_resource_tokens_fail_closed(self) -> None:
        cases: tuple[JsonObject, ...] = (
            {"active": False},
            {"active": "true"},
            {"iss": "https://wrong.example"},
            {"aud": ["another-resource"]},
            {"exp": 1},
            {"iat": int(time.time()) + 600},
            {"nbf": int(time.time()) + 600},
            {"sub": ""},
            {self.settings.roles_claim_path[0]: {}},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                self.fixture.introspection_payload = {**self.payload, **changes}
                with self.assertRaises(TokenVerificationError):
                    OidcTokenVerifier(self.settings).verify("opaque-test-token")

    def test_revocation_is_observed_after_short_cache_window(self) -> None:
        verifier = OidcTokenVerifier(self.settings)
        verifier.verify("opaque-test-token")
        self.fixture.introspection_payload = {"active": False}
        with (
            patch("briareus_oidc.verifier.time.monotonic", return_value=10**12),
            self.assertRaises(TokenVerificationError),
        ):
            verifier.verify("opaque-test-token")
        self.assertEqual(self.fixture.introspection_requests, 2)

    def test_provider_failure_is_not_cached_or_exposed(self) -> None:
        verifier = OidcTokenVerifier(self.settings)
        self.fixture.introspection_status = 500
        with self.assertRaises(TokenVerificationError) as error:
            verifier.verify("sensitive-opaque-test-token")
        self.assertNotIn("sensitive", str(error.exception))
        self.fixture.introspection_status = 200
        self.assertEqual(verifier.verify("sensitive-opaque-test-token").subject, "user-1")
        self.assertEqual(self.fixture.introspection_requests, 2)

    def test_introspection_credentials_are_required_only_in_introspection_mode(self) -> None:
        self.fixture.settings.validate_bootstrap()
        for changes in (
            {"introspection_client_id": ""},
            {"introspection_client_secret": SecretStr("")},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.settings.model_copy(update=changes).validate_bootstrap()
