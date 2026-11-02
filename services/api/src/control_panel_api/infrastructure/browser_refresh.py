"""Valkey CAS/lease and pinned provider adapters for refresh rotation."""

from __future__ import annotations

import json
from contextlib import suppress
from dataclasses import replace
from typing import TYPE_CHECKING, Literal

from pydantic import SecretStr
from valkey.exceptions import ValkeyError

from control_panel_api._oidc_refresh import refresh_login
from control_panel_api.domain.browser_refresh import RefreshSnapshot
from control_panel_api.domain.native_login import SecretText
from control_panel_api.domain.oidc_identity import OidcSessionStoreUnavailable, VerifiedOidcLogin
from control_panel_api.infrastructure._oidc_bindings import _ProviderBinding
from control_panel_api.infrastructure.browser_records import StoredBrowserSession, browser_record
from control_panel_api.infrastructure.browser_session_preparation import prepare_browser_session
from control_panel_api.infrastructure.browser_storage import BrowserStorageContext
from control_panel_api.infrastructure.valkey_scripts import eval_script

if TYPE_CHECKING:
    from control_panel_api._oidc import RauthyOidcAdapter

_CAS = (
    "if redis.call('GET',KEYS[1])~=ARGV[1] then return 0 end "
    "redis.call('SET',KEYS[1],ARGV[2],'PXAT',ARGV[3]); return 1"
)


class ValkeyRefreshSessions:
    def __init__(self, storage: BrowserStorageContext) -> None:
        self._storage = storage

    async def read(self, ticket: str) -> RefreshSnapshot | None:
        try:
            raw = await self._storage.client.get(self._storage.key("session", ticket))
            if not isinstance(raw, str) or len(raw) > 98304:
                return None
            record = browser_record(raw, StoredBrowserSession)
            deadlines = (
                record.expires_at,
                record.session_expires_at,
                record.refresh.not_before if record.refresh else None,
            )
            if any(value is not None and value.tzinfo is None for value in deadlines):
                raise ValueError("Stored identity has an ambiguous expiry")
            return RefreshSnapshot(
                raw,
                record.issuer,
                record.client_id,
                record.subject,
                record.expires_at,
                record.session_expires_at or record.expires_at,
                SecretStr(record.refresh.token) if record.refresh else None,
                record.refresh.not_before if record.refresh else None,
                bool(record.refresh_attempt),
            )
        except (ValkeyError, ValueError, TypeError, KeyError):
            raise OidcSessionStoreUnavailable("Session renewal unavailable") from None

    async def acquire(self, ticket: str, marker: str) -> bool:
        try:
            return bool(
                await self._storage.client.set(
                    self._storage.key("refresh-lock", ticket),
                    marker,
                    nx=True,
                    ex=25,
                )
            )
        except ValkeyError:
            raise OidcSessionStoreUnavailable("Session renewal unavailable") from None

    async def changed(
        self, ticket: str, snapshot: RefreshSnapshot
    ) -> Literal["same", "changed", "deleted"]:
        try:
            raw = await self._storage.client.get(self._storage.key("session", ticket))
        except ValkeyError:
            raise OidcSessionStoreUnavailable("Session renewal unavailable") from None
        if raw is None:
            return "deleted"
        return "same" if raw == snapshot.version else "changed"

    async def _swap(self, ticket: str, previous: RefreshSnapshot, raw: str) -> bool:
        try:
            result = await eval_script(
                self._storage.client,
                _CAS,
                1,
                self._storage.key("session", ticket),
                previous.version,
                raw,
                int(previous.hard_deadline.timestamp() * 1000),
            )
        except ValkeyError:
            raise OidcSessionStoreUnavailable("Session renewal unavailable") from None
        return bool(result == 1)

    async def mark(
        self, ticket: str, snapshot: RefreshSnapshot, marker: str
    ) -> RefreshSnapshot | None:
        value = browser_record(snapshot.version, StoredBrowserSession)
        value.refresh_attempt = marker
        raw = json.dumps(value.model_dump(mode="json", exclude_unset=True), separators=(",", ":"))
        return (
            replace(snapshot, version=raw, attempted=True)
            if await self._swap(ticket, snapshot, raw)
            else None
        )

    async def restore(
        self, ticket: str, original: RefreshSnapshot, attempted: RefreshSnapshot
    ) -> None:
        await self._swap(ticket, attempted, original.version)

    async def commit(
        self, ticket: str, attempted: RefreshSnapshot, login: VerifiedOidcLogin
    ) -> bool:
        prepared = prepare_browser_session(
            login.identity,
            resource=login.resource,
            refresh=login.refresh,
        )
        replacement = prepared.record
        replacement.session_expires_at = attempted.hard_deadline
        raw = json.dumps(
            replacement.model_dump(mode="json", exclude_unset=True), separators=(",", ":")
        )
        return await self._swap(ticket, attempted, raw)

    async def release(self, ticket: str, marker: str) -> None:
        with suppress(ValkeyError):
            await eval_script(
                self._storage.client,
                "if redis.call('GET',KEYS[1])==ARGV[1] then "
                "return redis.call('DEL',KEYS[1]) end return 0",
                1,
                self._storage.key("refresh-lock", ticket),
                marker,
            )

    async def delete(self, ticket: str) -> None:
        await self._storage.client.delete(self._storage.key("session", ticket))


class RauthyIdentityRefresh(_ProviderBinding["RauthyOidcAdapter"]):
    _provider: RauthyOidcAdapter

    async def refresh(self, token: SecretText, subject: str) -> VerifiedOidcLogin:
        return await refresh_login(
            self._provider, token=SecretStr(token.get_secret_value()), subject=subject
        )
