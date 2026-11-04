from __future__ import annotations

import time
import unittest
from unittest.mock import patch

import jwt
from briareus_json_values import JsonObject
from briareus_zitadel_tokens import (
    TokenVerificationError,
    ZitadelTokenSettings,
    ZitadelTokenVerifier,
)
from cryptography.hazmat.primitives.asymmetric import rsa
from zitadel_test_support import ZitadelTokenFixture


class ZitadelAccessTokenContracts(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = ZitadelTokenFixture()
        self.addCleanup(self.fixture.close)
        self.verifier = ZitadelTokenVerifier(self.fixture.settings)

    def test_signed_project_and_organization_grants_authorize_new_subjects(self) -> None:
        principal = self.verifier.verify(self.fixture.token({"sub": "newly-granted-user"}))
        self.assertEqual(principal.subject, "newly-granted-user")
        self.assertEqual(principal.username, "newly-granted-user")
        self.assertEqual(principal.organization_id, self.fixture.settings.organization_id)
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
            {settings.roles_claim: {"access": {"other-organization": "other.test"}}},
            {settings.roles_claim: {"unrelated-role": {settings.organization_id: "example.test"}}},
            {
                settings.roles_claim: None,
                "urn:zitadel:iam:org:project:roles": {
                    "access": {settings.organization_id: "example.test"}
                },
            },
            {
                settings.roles_claim: None,
                "urn:zitadel:iam:org:project:other:roles": {
                    "access": {settings.organization_id: "example.test"}
                },
            },
        )
        for overrides in invalid_grants:
            with self.subTest(overrides=overrides), self.assertRaises(TokenVerificationError):
                self.verifier.verify(self.fixture.token(overrides))

    def test_id_tokens_missing_access_token_claims_and_symmetric_algorithms_are_rejected(
        self,
    ) -> None:
        for field in ("exp", "nbf", "iat", "jti", "azp", "sub"):
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

    def test_algorithm_and_audience_configuration_fail_closed(self) -> None:
        for changes in ({"algorithms": ("HS256",)}, {"audience": "another-project"}):
            settings = self.fixture.settings.model_copy(update=changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                ZitadelTokenVerifier(settings)
        settings = ZitadelTokenSettings(
            issuer_url="http://untrusted-network", project_id="p", organization_id="o"
        )
        with self.assertRaises(ValueError):
            ZitadelTokenVerifier(settings)
