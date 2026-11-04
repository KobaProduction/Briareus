from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from typing import Protocol

from control_panel_api.domain.identity import (
    AuthorizationStart,
    IdentityGrant,
    LoginTransaction,
    PanelIdentitySession,
)


class IdentityFlowError(RuntimeError):
    pass


class PanelIdentityProvider(Protocol):
    def authorization_url(self, transaction: LoginTransaction) -> str: ...
    def exchange(self, code: str, transaction: LoginTransaction) -> IdentityGrant: ...
    def logout(self, grant: IdentityGrant) -> str: ...


class IdentitySessionRepository(Protocol):
    def put_transaction(self, transaction: LoginTransaction) -> None: ...
    def consume_transaction(self, state: str) -> LoginTransaction | None: ...
    def put_session(self, session: PanelIdentitySession) -> None: ...
    def get_session(self, identifier: str) -> PanelIdentitySession | None: ...
    def delete_session(self, identifier: str) -> None: ...


def pkce_challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")


class PanelIdentityService:
    def __init__(
        self,
        repository: IdentitySessionRepository,
        provider: PanelIdentityProvider,
        *,
        issuer: str,
        allowed_subjects: tuple[str, ...],
    ) -> None:
        self.repository = repository
        self.provider = provider
        self.issuer = issuer
        self.allowed_subjects = allowed_subjects

    def begin(self) -> AuthorizationStart:
        transaction = LoginTransaction(
            secrets.token_urlsafe(32),
            secrets.token_urlsafe(48),
            secrets.token_urlsafe(32),
            int(time.time()) + 300,
        )
        self.repository.put_transaction(transaction)
        return AuthorizationStart(transaction.state, self.provider.authorization_url(transaction))

    def complete(self, *, cookie_state: str, state: str, code: str) -> PanelIdentitySession:
        if not cookie_state or not state or not hmac.compare_digest(cookie_state, state):
            raise IdentityFlowError("identity transaction does not match this browser")
        transaction = self.repository.consume_transaction(state)
        if transaction is None or transaction.expires_at <= time.time():
            raise IdentityFlowError("identity transaction expired or was already used")
        grant = self.provider.exchange(code, transaction)
        if not self._grant_allowed(grant):
            raise IdentityFlowError("identity does not have Control Panel access")
        session = PanelIdentitySession(secrets.token_urlsafe(32), secrets.token_urlsafe(32), grant)
        self.repository.put_session(session)
        return session

    def current(self, identifier: str) -> PanelIdentitySession | None:
        if not identifier:
            return None
        session = self.repository.get_session(identifier)
        if session is None:
            return None
        if not self._grant_allowed(session.grant):
            self.repository.delete_session(identifier)
            return None
        return session

    def _grant_allowed(self, grant: IdentityGrant) -> bool:
        return (
            grant.issuer == self.issuer
            and grant.subject in self.allowed_subjects
            and grant.expires_at > time.time()
        )

    def require_csrf(self, session: PanelIdentitySession, value: str) -> None:
        if not value or not hmac.compare_digest(session.csrf_token, value):
            raise IdentityFlowError("Control Panel CSRF token is invalid")

    def logout(self, session: PanelIdentitySession) -> str:
        self.repository.delete_session(session.identifier)
        return self.provider.logout(session.grant)
