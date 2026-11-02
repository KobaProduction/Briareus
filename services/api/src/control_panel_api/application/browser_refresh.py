"""Serialize rotating refresh across tabs, retaining send intent across lost replies."""

import asyncio
import secrets
from datetime import UTC, datetime
from typing import Literal, Protocol

from control_panel_api.domain.browser_refresh import RefreshSnapshot
from control_panel_api.domain.native_login import SecretText
from control_panel_api.domain.oidc_identity import (
    OidcIdentityRejected,
    OidcSessionStoreUnavailable,
    RefreshNotDispatched,
    VerifiedOidcLogin,
)


class RefreshSessions(Protocol):
    async def read(self, ticket: str) -> RefreshSnapshot | None: ...
    async def acquire(self, ticket: str, marker: str) -> bool: ...
    async def changed(
        self, ticket: str, snapshot: RefreshSnapshot
    ) -> Literal["same", "changed", "deleted"]: ...
    async def mark(
        self, ticket: str, snapshot: RefreshSnapshot, marker: str
    ) -> RefreshSnapshot | None: ...
    async def restore(
        self, ticket: str, original: RefreshSnapshot, attempted: RefreshSnapshot
    ) -> None: ...
    async def commit(
        self, ticket: str, attempted: RefreshSnapshot, login: VerifiedOidcLogin
    ) -> bool: ...
    async def release(self, ticket: str, marker: str) -> None: ...
    async def delete(self, ticket: str) -> None: ...


class IdentityRefresh(Protocol):
    async def refresh(self, token: SecretText, subject: str) -> VerifiedOidcLogin: ...


class BrowserRefresh:
    def __init__(
        self, sessions: RefreshSessions, provider: IdentityRefresh, *, issuer: str, client_id: str
    ) -> None:
        self._sessions = sessions
        self._provider = provider
        self._issuer = issuer
        self._client = client_id

    async def _wait(self, ticket: str, snapshot: RefreshSnapshot) -> int | None:
        for _ in range(20):
            await asyncio.sleep(0.1)
            change = await self._sessions.changed(ticket, snapshot)
            if change == "deleted":
                return None
            if change == "changed":
                return snapshot.remaining(datetime.now(UTC))
        raise OidcSessionStoreUnavailable("Session renewal in progress")

    async def _refresh(self, ticket: str, snapshot: RefreshSnapshot, marker: str) -> int | None:
        if await self._sessions.changed(ticket, snapshot) != "same":
            return snapshot.remaining(datetime.now(UTC))
        if snapshot.attempted:
            if snapshot.expires_at <= datetime.now(UTC):
                raise OidcIdentityRejected("Renewal outcome unavailable; sign in again")
            return snapshot.remaining(datetime.now(UTC))
        attempted = await self._sessions.mark(ticket, snapshot, marker)
        if attempted is None or snapshot.token is None:
            return None
        try:
            login = await self._provider.refresh(snapshot.token, snapshot.subject)
        except RefreshNotDispatched:
            await self._sessions.restore(ticket, snapshot, attempted)
            raise OidcSessionStoreUnavailable("Provider connection unavailable") from None
        changed = await self._sessions.commit(ticket, attempted, login)
        return snapshot.remaining(datetime.now(UTC)) if changed else None

    async def renew(self, ticket: str) -> int | None:
        marker = secrets.token_urlsafe(32)
        acquired = False
        try:
            snapshot = await self._sessions.read(ticket)
            now = datetime.now(UTC)
            if snapshot is None or not snapshot.is_current(self._issuer, self._client, now):
                return None
            if not snapshot.renewal_due(now):
                return snapshot.remaining(now)
            acquired = await self._sessions.acquire(ticket, marker)
            if not acquired:
                return await self._wait(ticket, snapshot)
            return await self._refresh(ticket, snapshot, marker)
        except OidcIdentityRejected:
            await self._sessions.delete(ticket)
            raise
        finally:
            if acquired:
                await self._sessions.release(ticket, marker)
