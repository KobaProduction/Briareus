"""Test-only external RSA authority with preloaded JWKS; no application auth storage."""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import jwt
from briareus_zitadel_tokens import ZitadelTokenSettings, ZitadelTokenVerifier
from control_panel_api.application.identity import PanelOidcSettings, PanelTokenIdentity
from cryptography.hazmat.primitives.asymmetric import rsa

ISSUER = "https://identity.example.test"
SUBJECT = "verified-user-123"
ORIGIN = "https://briareus.example.test"
PROJECT = "test-project"
ORGANIZATION = "test-organization"


class TokenAuthorityHarness:
    def __init__(self) -> None:
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.settings = ZitadelTokenSettings(
            issuer_url=ISSUER,
            project_id=PROJECT,
            organization_id=ORGANIZATION,
        )
        self.verifier = ZitadelTokenVerifier(self.settings)
        jwk = jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key(), as_dict=True)
        jwk.update(kid="external-rsa", alg="RS256", use="sig")
        assert self.verifier.jwks.jwk_set_cache is not None
        self.verifier.jwks.jwk_set_cache.put({"keys": [jwk]})
        self.identity = PanelTokenIdentity(
            self.verifier,
            PanelOidcSettings(public_base_url=ORIGIN, client_id="public-spa"),
            ISSUER,
            PROJECT,
            PROJECT,
        )
        self.now = time.time()
        self.clock = patch(
            "briareus_zitadel_tokens.verifier.time",
            SimpleNamespace(time=lambda: self.now),
        )
        self.clock.start()

    def authenticate(self, *, role: str = "access", lifetime: int = 300) -> str:
        now = int(time.time())
        return jwt.encode(
            {
                "iss": ISSUER,
                "sub": SUBJECT,
                "aud": PROJECT,
                "azp": "public-spa",
                "iat": now,
                "nbf": now,
                "exp": now + lifetime,
                "jti": uuid4().hex,
                "preferred_username": "operator",
                "name": "Briareus operator",
                self.settings.roles_claim: {role: {ORGANIZATION: "example.test"}},
            },
            self.key,
            algorithm="RS256",
            headers={"kid": "external-rsa"},
        )

    def expire(self) -> None:
        self.now = time.time() + 600

    def close(self) -> None:
        self.clock.stop()
