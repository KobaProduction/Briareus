from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from briareus_oidc import (
    OidcTokenSettings,
    OidcTokenVerifier,
    TokenAccessDenied,
    TokenVerificationError,
)
from briareus_oidc.discovery import ProviderMetadata, discover
from zitadel_test_support import ZitadelTokenFixture


class OidcProviderContracts(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = ZitadelTokenFixture()
        self.addCleanup(self.fixture.close)

    def test_nested_roles_and_discovered_keys_without_vendor_claims(self) -> None:
        self.fixture.jwks_path = "/realms/briareus/protocol/openid-connect/certs"
        settings = self.fixture.settings.model_copy(
            update={
                "roles_claim_path": ("resource_access", "briareus-api", "roles"),
                "roles_format": "list",
                "roles_organization_id": "",
            }
        )
        verifier = OidcTokenVerifier(settings)
        token = self.fixture.token(
            {
                "azp": "public-panel",
                "resource_access": {"briareus-api": {"roles": ["access"]}},
            },
            omit=("client_id", "nbf", "jti", self.fixture.settings.roles_claim_path[0]),
        )
        self.assertEqual(verifier.verify(token).roles, ("access",))
        self.assertEqual(verifier.verify(token).client_id, "public-panel")
        self.assertEqual(self.fixture.discovery_requests, 1)
        self.assertEqual(self.fixture.requests, 1)
        for changes in (
            {"resource_access": {"other-api": {"roles": ["access"]}}},
            {"resource_access": {"briareus-api": {"roles": ["viewer"]}}},
            {"resource_access": {"briareus-api": {"roles": "access"}}},
            {"aud": "public-panel"},
        ):
            with self.subTest(changes=changes), self.assertRaises(TokenVerificationError):
                verifier.verify(self.fixture.token(changes))

    def test_generic_environment_configuration_has_no_provider_ids(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OIDC_ISSUER_URL": "https://identity.example/realms/briareus",
                "OIDC_AUDIENCE": "briareus-api",
                "OIDC_SCOPES": "openid,profile",
                "OIDC_ROLES_CLAIM_PATH": '["realm_access","roles"]',
            },
            clear=True,
        ):
            settings = OidcTokenSettings()
        settings.validate_bootstrap()
        self.assertEqual(settings.authorization_scopes, ("openid", "profile"))
        self.assertEqual(settings.roles_claim_path, ("realm_access", "roles"))

    def test_only_verified_tokens_can_report_missing_application_access(self) -> None:
        verifier = OidcTokenVerifier(self.fixture.settings)
        role_claim = self.fixture.settings.roles_claim_path[0]
        with self.assertRaises(TokenAccessDenied):
            verifier.verify(self.fixture.token(omit=(role_claim,)))
        for changes in ({"aud": "wrong-api"}, {"exp": 1}, {"iss": "https://wrong.example"}):
            with self.subTest(changes=changes), self.assertRaises(TokenVerificationError) as error:
                verifier.verify(self.fixture.token(changes, omit=(role_claim,)))
            self.assertNotIsInstance(error.exception, TokenAccessDenied)

    def test_plain_role_list_and_configured_required_role(self) -> None:
        settings = self.fixture.settings.model_copy(
            update={
                "roles_claim_path": ("permissions",),
                "roles_format": "list",
                "roles_organization_id": "",
                "required_role": "node:operate",
            }
        )
        principal = OidcTokenVerifier(settings).verify(
            self.fixture.token({"permissions": ["node:operate"]})
        )
        self.assertEqual(principal.roles, ("node:operate",))

    def test_discovery_rejects_mismatched_issuer_and_insecure_keys(self) -> None:
        self.fixture.discovery_issuer = "https://another-issuer.example"
        with self.assertRaises(TokenVerificationError):
            OidcTokenVerifier(self.fixture.settings).verify(self.fixture.token())
        self.fixture.discovery_issuer = None
        self.fixture.jwks_uri = "http://non-local.example/keys"
        with self.assertRaises(TokenVerificationError):
            OidcTokenVerifier(self.fixture.settings).verify(self.fixture.token())
        self.assertEqual(self.fixture.requests, 0)

    def test_metadata_expiry_refreshes_changed_jwks_location(self) -> None:
        verifier = OidcTokenVerifier(self.fixture.settings)
        verifier.verify(self.fixture.token())
        self.fixture.jwks_path = "/rotated/keys"
        with patch("briareus_oidc.discovery.time.monotonic", return_value=10**12):
            verifier.verify(self.fixture.token())
        self.assertEqual(self.fixture.discovery_requests, 2)
        self.assertEqual(self.fixture.requests, 2)

    def test_discovery_supports_issuer_realm_path(self) -> None:
        issuer = "https://identity.example/realms/briareus"
        metadata = ProviderMetadata(issuer=issuer, jwks_uri=issuer + "/certs")
        with patch("briareus_oidc.discovery.httpx.stream") as stream:
            response = stream.return_value.__enter__.return_value
            response.iter_bytes.return_value = [metadata.model_dump_json().encode()]
            self.assertEqual(discover(issuer), metadata)
        self.assertEqual(stream.call_args.args[1], issuer + "/.well-known/openid-configuration")
