"""Browser identity lifecycle; Rauthy facts never imply Platform membership."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from control_panel_api.domain.oidc_identity import (
    OidcAuthorizationAttempt,
    OidcIdentityKeysUnavailable,
    OidcIdentityRejected,
    OidcProviderUnavailable,
    OidcSessionStoreUnavailable,
    PrivateOidcPending,
    VerifiedOidcLogin,
)
from control_panel_api.domain.platform_authority import PanelOidcSession


class BrowserIdentityPort(Protocol):
    async def prepare(self) -> OidcAuthorizationAttempt: ...
    async def save(self, attempt: OidcAuthorizationAttempt) -> None: ...
    async def consume(self, state: str) -> PrivateOidcPending | None: ...
    async def authenticate(
        self, transaction: PrivateOidcPending, code: str, issuer: str
    ) -> VerifiedOidcLogin: ...
    async def create(self, login: VerifiedOidcLogin) -> tuple[str, int]: ...
    async def renew(self, ticket: str) -> int | None: ...
    async def identity(self, ticket: str) -> PanelOidcSession | None: ...
    async def delete(self, ticket: str) -> None: ...
    async def delete_native(self, state: str) -> None: ...


@dataclass(frozen=True, slots=True)
class BrowserIdentityFailure:
    status: int
    detail: str = ""
    code: str = ""
    clear_cookie: bool = False


@dataclass(frozen=True, slots=True)
class BrowserSessionCreated:
    ticket: str
    seconds: int


@dataclass(frozen=True, slots=True)
class BrowserIdentityStatus:
    identity: PanelOidcSession
    renewed_seconds: int | None


class BrowserIdentity:
    def __init__(self, port: BrowserIdentityPort, *, issuer: str, client_id: str) -> None:
        self._port = port
        self._issuer = issuer
        self._client_id = client_id

    async def start(self) -> OidcAuthorizationAttempt | BrowserIdentityFailure:
        try:
            attempt = await self._port.prepare()
            await self._port.save(attempt)
            return attempt
        except (OidcProviderUnavailable, OidcSessionStoreUnavailable):
            return BrowserIdentityFailure(503, detail="OIDC login unavailable")

    async def callback(
        self, state: str, code: str, issuer: str
    ) -> BrowserSessionCreated | BrowserIdentityFailure:
        try:
            transaction = await self._port.consume(state)
            if transaction is None:
                return BrowserIdentityFailure(401, detail="OIDC state already used or expired")
            login = await self._port.authenticate(transaction, code, issuer)
            if transaction.expires_at <= datetime.now(UTC):
                raise OidcIdentityRejected("original transaction expired during OAuth exchange")
            ticket, seconds = await self._port.create(login)
            return BrowserSessionCreated(ticket, seconds)
        except (OidcProviderUnavailable, OidcIdentityKeysUnavailable, OidcSessionStoreUnavailable):
            return BrowserIdentityFailure(503, detail="OIDC identity service unavailable")
        except OidcIdentityRejected:
            return BrowserIdentityFailure(401, detail="OIDC identity verification failed")

    async def current(self, ticket: str) -> BrowserIdentityStatus | BrowserIdentityFailure:
        try:
            age = await self._port.renew(ticket)
            identity = await self._port.identity(ticket)
        except (OidcSessionStoreUnavailable, OidcProviderUnavailable, OidcIdentityKeysUnavailable):
            return BrowserIdentityFailure(503, code="OIDC_SESSION_STORE_UNAVAILABLE")
        except OidcIdentityRejected:
            return BrowserIdentityFailure(401, code="OIDC_SESSION_EXPIRED")
        if identity is None:
            return BrowserIdentityFailure(401, code="OIDC_SESSION_EXPIRED")
        if identity.issuer.rstrip("/") == self._issuer and identity.client_id == self._client_id:
            return BrowserIdentityStatus(identity, age)
        try:
            await self._port.delete(ticket)
        except OidcSessionStoreUnavailable:
            return BrowserIdentityFailure(503, code="OIDC_STALE_SESSION_REVOCATION_UNAVAILABLE")
        return BrowserIdentityFailure(401, code="OIDC_SESSION_REALM_MISMATCH", clear_cookie=True)

    async def logout(
        self, ticket: str | None, native_state: str | None
    ) -> BrowserIdentityFailure | None:
        if native_state is not None:
            try:
                await self._port.delete_native(native_state)
            except OidcSessionStoreUnavailable:
                return BrowserIdentityFailure(503, detail="native Init logout not confirmed")
        if ticket is not None:
            try:
                await self._port.delete(ticket)
            except OidcSessionStoreUnavailable:
                return BrowserIdentityFailure(503, detail="OIDC logout not confirmed")
        return None
