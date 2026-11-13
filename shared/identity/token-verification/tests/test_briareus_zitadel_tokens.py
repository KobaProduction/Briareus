from __future__ import annotations

import time
import unittest
from unittest.mock import patch

import httpx
import jwt
from briareus_json_values import JsonObject
from briareus_oidc import (
    OidcTokenSettings,
    OidcTokenVerifier,
    TokenVerificationError,
)
from cryptography.hazmat.primitives.asymmetric import rsa
from zitadel_test_support import ZitadelTokenFixture


class ZitadelAccessTokenContracts(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = ZitadelTokenFixture()
        self.addCleanup(self.fixture.close)
        self.verifier = OidcTokenVerifier(self.fixture.settings)

    def test_token_rejection_categories_are_specific_and_do_not_include_claims(self) -> None:
        now = int(time.time())
        cases: tuple[tuple[JsonObject, str], ...] = (
            ({"exp": now - 60}, "expired"),
            ({"nbf": now + 600}, "not_yet_valid"),
            ({"aud": "other-project"}, "invalid_audience"),
            ({"iss": "https://other-issuer.example"}, "invalid_issuer"),
            ({"client_id": None}, "invalid_claims"),
            ({self.fixture.settings.roles_claim_path[0]: {}}, "missing_grant"),
        )
        for changes, expected_reason in cases:
            with self.subTest(reason=expected_reason):
                with self.assertRaises(TokenVerificationError) as error:
                    self.verifier.verify(self.fixture.token(changes))
                self.assertEqual(error.exception.reason, expected_reason)
                self.assertNotIn("user-1", str(error.exception))
                self.assertNotIn("registered-public-client", str(error.exception))

    def test_signing_key_provider_failure_uses_safe_reason(self) -> None:
        with patch(
            "briareus_oidc.verifier.ProviderKeys.client",
            side_effect=httpx.ConnectError("secret-provider-detail"),
        ), self.assertRaises(TokenVerificationError) as error:
            self.verifier.verify(self.fixture.token())
        self.assertEqual(error.exception.reason, "provider_unavailable")
        self.assertNotIn("secret-provider-detail", str(error.exception))

    def test_malformed_signature_and_algorithm_have_distinct_safe_reasons(self) -> None:
        signed = self.fixture.token()
        header, payload, signature = signed.split(".")
        corrupted = ("A" if signature[0] != "A" else "B") + signature[1:]
        symmetric = jwt.encode(
            {"sub": "user"}, "test-only-long-secret-32-characters", algorithm="HS256"
        )
        tokens = (
            ("not-a-jwt", "invalid_token"),
            (".".join((header, payload, corrupted)), "invalid_signature"),
            (symmetric, "invalid_algorithm"),
        )
        for token, expected_reason in tokens:
            with self.subTest(reason=expected_reason):
                with self.assertRaises(TokenVerificationError) as error:
                    self.verifier.verify(token)
                self.assertEqual(error.exception.reason, expected_reason)
                self.assertNotIn(token, str(error.exception))

    def test_signed_project_and_organization_grants_authorize_new_subjects(self) -> None:
        principal = self.verifier.verify(self.fixture.token({"sub": "newly-granted-user"}))
        self.assertEqual(principal.subject, "newly-granted-user")
        self.assertEqual(principal.username, "newly-granted-user")
        self.assertEqual(principal.roles, ("access",))
        self.assertIn("access", principal.roles)
        self.assertTrue(principal.is_active())
        self.verifier.verify(self.fixture.token())
        self.assertEqual(self.fixture.requests, 1)

    def test_issuer_audience_expiration_not_before_and_signature_are_enforced(self) -> None:
        now = int(time.time())
        invalid_claims: tuple[JsonObject, ...] = (
            {"iss": "https://another-issuer.example"},
            {"aud": "another-project"},
            {"exp": now - 1},
            {"nbf": now + 300},
            {"iat": now + 300},
        )
        for changes in invalid_claims:
            with self.subTest(changes=changes), self.assertRaises(TokenVerificationError):
                self.verifier.verify(self.fixture.token(changes))
        token = self.fixture.token()
        head, body, signature = token.split(".")
        signature = ("A" if signature[0] != "A" else "B") + signature[1:]
        with self.assertRaises(TokenVerificationError):
            self.verifier.verify(".".join((head, body, signature)))

    def test_another_project_or_organization_and_generic_roles_cannot_grant_access(self) -> None:
        settings = self.fixture.settings
        invalid_grants: tuple[JsonObject, ...] = (
            {settings.roles_claim_path[0]: {"access": {"other-organization": "other.test"}}},
            {
                settings.roles_claim_path[0]: {
                    "unrelated-role": {settings.roles_organization_id: "example.test"}
                }
            },
            {
                settings.roles_claim_path[0]: None,
                "urn:zitadel:iam:org:project:roles": {
                    "access": {settings.roles_organization_id: "example.test"}
                },
            },
            {
                settings.roles_claim_path[0]: None,
                "urn:zitadel:iam:org:project:other:roles": {
                    "access": {settings.roles_organization_id: "example.test"}
                },
            },
        )
        for overrides in invalid_grants:
            with self.subTest(overrides=overrides), self.assertRaises(TokenVerificationError):
                self.verifier.verify(self.fixture.token(overrides))

    def test_id_tokens_missing_access_token_claims_and_symmetric_algorithms_are_rejected(
        self,
    ) -> None:
        for field in ("exp", "iat", "client_id", "sub"):
            with self.subTest(field=field), self.assertRaises(TokenVerificationError):
                self.verifier.verify(self.fixture.token(omit=(field,)))
        symmetric = jwt.encode(
            {"sub": "user"}, "test-only-secret-that-is-at-least-32-bytes", algorithm="HS256"
        )
        with self.assertRaises(TokenVerificationError):
            self.verifier.verify(symmetric)
        self.assertEqual(self.fixture.requests, 1)

    def test_expired_key_set_refreshes_and_removed_signing_keys_are_not_cached_forever(
        self,
    ) -> None:
        first_token = self.fixture.token()
        self.verifier.verify(first_token)
        self.fixture.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.fixture.kid = "rotated"
        with patch("jwt.jwk_set_cache.time.monotonic", return_value=time.monotonic() + 301):
            self.verifier.verify(self.fixture.token())
            with self.assertRaises(TokenVerificationError):
                self.verifier.verify(first_token)
        self.assertEqual(self.fixture.requests, 2)

    def test_real_zitadel_client_id_and_legacy_azp_are_both_supported(self) -> None:
        principal = self.verifier.verify(self.fixture.token())
        self.assertNotIn("azp", principal.claims)
        self.assertEqual(principal.client_id, "registered-public-client")
        legacy = self.fixture.token({"azp": "legacy-client"}, omit=("client_id",))
        self.assertEqual(self.verifier.verify(legacy).client_id, "legacy-client")
        agreeing = self.fixture.token({"azp": "registered-public-client"})
        self.assertEqual(self.verifier.verify(agreeing).client_id, "registered-public-client")

    def test_missing_invalid_and_conflicting_client_identity_claims_fail_closed(self) -> None:
        invalid_claims: tuple[JsonObject, ...] = (
            {"client_id": "client-one", "azp": "client-two"},
            {"client_id": ""},
            {"client_id": 17},
            {"client_id": None},
            {"client_id": "registered-public-client", "azp": ""},
            {"client_id": "registered-public-client", "azp": 17},
            {"client_id": "registered-public-client", "azp": None},
        )
        for claims in invalid_claims:
            with self.subTest(claims=claims), self.assertRaises(TokenVerificationError):
                self.verifier.verify(self.fixture.token(claims))
        with self.assertRaises(TokenVerificationError):
            self.verifier.verify(self.fixture.token(omit=("client_id", "azp")))

    def test_algorithm_and_audience_configuration_fail_closed(self) -> None:
        for changes in ({"algorithms": ("HS256",)}, {"audience": ""}):
            settings = self.fixture.settings.model_copy(update=changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                OidcTokenVerifier(settings)
        settings = OidcTokenSettings(issuer_url="http://untrusted-network", audience="p")
        with self.assertRaises(ValueError):
            OidcTokenVerifier(settings)
