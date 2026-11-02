"""Explicit, isolated identity ports for BRI V1 behavioral contracts."""

from __future__ import annotations

import time
from dataclasses import replace
from urllib.parse import urlencode

from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from control_panel_api.application.identity import PanelIdentityService, pkce_challenge
from control_panel_api.domain.identity import IdentityGrant, LoginTransaction
from control_panel_api.infrastructure.crypto import FernetCredentialCipher
from control_panel_api.infrastructure.identity_sessions import SqlIdentitySessionRepository

ISSUER = "https://identity.example.test"
SUBJECT = "verified-user-123"
ORIGIN = "https://bri.example.test"


class IdentityProvider:
    def __init__(self) -> None:
        self.grant = IdentityGrant(
            SUBJECT,
            ISSUER,
            "BRI operator",
            int(time.time()) + 300,
            "test-access-token",
            "test-id-token",
            "test-refresh-token",
        )
        self.exchanges = 0
        self.logout_error = False

    def authorization_url(self, transaction: LoginTransaction) -> str:
        return (
            ISSUER
            + "/authorize?"
            + urlencode(
                {
                    "state": transaction.state,
                    "nonce": transaction.nonce,
                    "code_challenge": pkce_challenge(transaction.verifier),
                    "code_challenge_method": "S256",
                }
            )
        )

    def exchange(self, code: str, transaction: LoginTransaction) -> IdentityGrant:
        if not code or not transaction.nonce:
            raise ValueError("Incomplete identity exchange")
        self.exchanges += 1
        return self.grant

    def logout(self, grant: IdentityGrant) -> str:
        if self.logout_error:
            raise ValueError("Provider unavailable")
        return ISSUER + "/logout?subject=" + grant.subject


class IdentityHarness:
    def __init__(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.cipher = FernetCredentialCipher(Fernet.generate_key().decode())
        self.repository = SqlIdentitySessionRepository(self.engine, self.cipher)
        self.provider = IdentityProvider()
        self.service = PanelIdentityService(
            self.repository,
            self.provider,
            issuer=ISSUER,
            allowed_subjects=(SUBJECT,),
        )

    def authenticate(self) -> str:
        start = self.service.begin()
        session = self.service.complete(cookie_state=start.state, state=start.state, code="code")
        return session.identifier

    def expire(self, identifier: str) -> None:
        session = self.repository.get_session(identifier)
        if session is None:
            raise AssertionError("Missing test session")
        self.repository.delete_session(identifier)
        self.repository.put_session(
            replace(
                session,
                grant=replace(session.grant, expires_at=int(time.time()) - 1),
            )
        )

    def close(self) -> None:
        self.engine.dispose()
