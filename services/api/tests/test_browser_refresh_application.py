"""Rotating credentials are never re-dispatched after a lost reply or concurrent logout."""

import unittest
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Literal

from control_panel_api.application.browser_refresh import BrowserRefresh
from control_panel_api.domain.browser_refresh import RefreshSnapshot
from control_panel_api.domain.native_login import SecretText
from control_panel_api.domain.oidc_identity import (
    OidcIdentityRejected,
    OidcProviderUnavailable,
    OidcSessionStoreUnavailable,
    RefreshNotDispatched,
    VerifiedOidcIdentity,
    VerifiedOidcLogin,
)
from pydantic import SecretStr


@dataclass
class Sessions:
    snapshot: RefreshSnapshot | None
    released: bool = False

    async def read(self, _ticket: str) -> RefreshSnapshot | None:
        return self.snapshot

    async def acquire(self, _ticket: str, _marker: str) -> bool:
        return True

    async def changed(
        self, _ticket: str, snapshot: RefreshSnapshot
    ) -> Literal["same", "changed", "deleted"]:
        if self.snapshot is None:
            return "deleted"
        return "same" if self.snapshot.version == snapshot.version else "changed"

    async def mark(
        self, _ticket: str, snapshot: RefreshSnapshot, marker: str
    ) -> RefreshSnapshot | None:
        if self.snapshot != snapshot:
            return None
        self.snapshot = replace(snapshot, version=marker, attempted=True)
        return self.snapshot

    async def restore(
        self, _ticket: str, original: RefreshSnapshot, attempted: RefreshSnapshot
    ) -> None:
        if self.snapshot == attempted:
            self.snapshot = original

    async def commit(
        self, _ticket: str, attempted: RefreshSnapshot, _login: VerifiedOidcLogin
    ) -> bool:
        return self.snapshot == attempted

    async def release(self, _ticket: str, _marker: str) -> None:
        self.released = True

    async def delete(self, _ticket: str) -> None:
        self.snapshot = None

    def logout(self) -> None:
        self.snapshot = None


@dataclass
class Provider:
    result: VerifiedOidcLogin | Exception
    on_call: Callable[[], None] | None = None
    calls: int = 0

    async def refresh(self, token: SecretText, subject: str) -> VerifiedOidcLogin:
        assert token.get_secret_value() == "rotating" and subject == "subject"
        self.calls += 1
        if self.on_call is not None:
            self.on_call()
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def snapshot(*, attempted: bool = False, expired: bool = False) -> RefreshSnapshot:
    now = datetime.now(UTC)
    return RefreshSnapshot(
        "original",
        "https://issuer/",
        "client",
        "subject",
        now + timedelta(seconds=-1 if expired else 20),
        now + timedelta(hours=1),
        SecretStr("rotating"),
        now - timedelta(seconds=1),
        attempted,
    )


def login() -> VerifiedOidcLogin:
    return VerifiedOidcLogin(
        VerifiedOidcIdentity(
            "https://issuer/", "subject", "client", datetime.now(UTC) + timedelta(minutes=5)
        ),
        None,
    )


def use_case(sessions: Sessions, provider: Provider) -> BrowserRefresh:
    return BrowserRefresh(sessions, provider, issuer="https://issuer", client_id="client")


class RefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_uncertain_send_retains_intent_and_never_replays_rotating_token(self) -> None:
        sessions, provider = Sessions(snapshot()), Provider(OidcProviderUnavailable())
        service = use_case(sessions, provider)
        with self.assertRaises(OidcProviderUnavailable):
            await service.renew("ticket")
        self.assertTrue(sessions.released)
        self.assertIsNotNone(await service.renew("ticket"))
        self.assertEqual(provider.calls, 1)

    async def test_expired_uncertain_identity_is_deleted_without_provider_retry(self) -> None:
        sessions, provider = Sessions(snapshot(attempted=True, expired=True)), Provider(login())
        with self.assertRaises(OidcIdentityRejected):
            await use_case(sessions, provider).renew("ticket")
        self.assertIsNone(sessions.snapshot)
        self.assertEqual(provider.calls, 0)

    async def test_confirmed_non_dispatch_restores_only_its_own_send_intent(self) -> None:
        original = snapshot()
        sessions, provider = Sessions(original), Provider(RefreshNotDispatched())
        with self.assertRaises(OidcSessionStoreUnavailable):
            await use_case(sessions, provider).renew("ticket")
        self.assertEqual(sessions.snapshot, original)
        self.assertTrue(sessions.released)

    async def test_late_provider_success_cannot_resurrect_concurrent_logout(self) -> None:
        sessions = Sessions(snapshot())
        provider = Provider(login(), on_call=sessions.logout)
        self.assertIsNone(await use_case(sessions, provider).renew("ticket"))
        self.assertIsNone(sessions.snapshot)
        self.assertTrue(sessions.released)
