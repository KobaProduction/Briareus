"""Atomic escrow persistence retains the original browser record TTL and generation."""

import json

from pydantic import Field, SecretStr
from valkey.exceptions import ValkeyError

from control_panel_api._oidc import RauthyOidcAdapter
from control_panel_api.domain.oidc_identity import (
    PrivateOidcResourceCredential,
    VerifiedOidcIdentity,
)
from control_panel_api.domain.resource_escrow import (
    CachedResource,
    EscrowSnapshot,
    ResourceCredentialUnavailable,
)
from control_panel_api.infrastructure._oidc_bindings import _BrowserSessionDelete
from control_panel_api.infrastructure.browser_records import (
    StoredBrowserResource as StoredPrimaryResource,
)
from control_panel_api.infrastructure.browser_records import (
    StoredBrowserSession,
    StoredResource,
    browser_record,
)
from control_panel_api.infrastructure.browser_renewal import renew_browser_session
from control_panel_api.infrastructure.browser_sessions import ValkeyBrowserSessions
from control_panel_api.infrastructure.browser_storage import BrowserStorageContext
from control_panel_api.infrastructure.valkey_scripts import eval_script

MAX_SESSION_BYTES = 98304
COMMIT = (
    "if redis.call('GET',KEYS[1])~=ARGV[1] then return 0 end "
    "local ttl=redis.call('PTTL',KEYS[1]); if ttl<=0 then return 0 end "
    "redis.call('SET',KEYS[1],ARGV[2],'PX',ttl); return 1"
)


class StoredEscrow(StoredBrowserSession):
    resource: StoredPrimaryResource = Field(...)


def stored_escrow(raw: str) -> StoredEscrow:
    value = browser_record(raw, StoredEscrow)
    records = (value.resource, *value.mcp_resources.values())
    if value.expires_at.tzinfo is None or any(
        record.expires_at.tzinfo is None for record in records
    ):
        raise ValueError("Unambiguous credential expiry required")
    if any(
        not record.bearer.isascii() or any(char.isspace() for char in record.bearer)
        for record in records
    ):
        raise ValueError("Private resource bearer malformed")
    return value


class ValkeyResourceSessions(_BrowserSessionDelete):
    def __init__(
        self,
        sessions: ValkeyBrowserSessions,
        provider: RauthyOidcAdapter,
        storage: BrowserStorageContext,
    ) -> None:
        self._sessions, self._provider, self._storage = sessions, provider, storage

    async def identity(self, ticket: str) -> VerifiedOidcIdentity | None:
        await renew_browser_session(self._storage, ticket, self._provider)
        session = await self._sessions.get_session(ticket)
        if session is None:
            return None
        return VerifiedOidcIdentity(
            session.issuer, session.subject, session.client_id, session.expires_at
        )

    async def primary(
        self, ticket: str, identity: VerifiedOidcIdentity, audience: str
    ) -> PrivateOidcResourceCredential | None:
        return await self._sessions.get_resource_credential(
            ticket, issuer=identity.issuer, client_id=identity.client_id, audience=audience
        )

    async def read(self, ticket: str, allowed: frozenset[str]) -> EscrowSnapshot | None:
        try:
            raw = await self._storage.client.get(self._storage.key("session", ticket))
            if not isinstance(raw, str) or len(raw) > MAX_SESSION_BYTES:
                return None
            value = stored_escrow(raw)
            if not set(value.mcp_resources) <= allowed or len(value.mcp_resources) > len(allowed):
                return None
            return EscrowSnapshot(
                raw,
                value.issuer,
                value.subject,
                value.client_id,
                value.expires_at,
                value.resource.expires_at,
                SecretStr(value.resource.bearer),
                tuple(
                    CachedResource(audience, SecretStr(resource.bearer), resource.expires_at)
                    for audience, resource in value.mcp_resources.items()
                ),
            )
        except (ValkeyError, ValueError, TypeError, KeyError):
            raise ResourceCredentialUnavailable("Private resource escrow unavailable") from None

    async def commit(
        self, ticket: str, snapshot: EscrowSnapshot, resource: PrivateOidcResourceCredential
    ) -> bool:
        try:
            value = stored_escrow(snapshot.version)
            value.mcp_resources = {
                **value.mcp_resources,
                resource.audience: StoredResource(
                    bearer=resource.bearer.get_secret_value(), expires_at=resource.expires_at
                ),
            }
            updated = json.dumps(
                value.model_dump(mode="json", exclude_unset=True), separators=(",", ":")
            )
            if len(updated) > MAX_SESSION_BYTES:
                return False
            return (
                await eval_script(
                    self._storage.client,
                    COMMIT,
                    1,
                    self._storage.key("session", ticket),
                    snapshot.version,
                    updated,
                )
                == 1
            )

        except (ValkeyError, ValueError, TypeError, KeyError):
            raise ResourceCredentialUnavailable("Private resource escrow unavailable") from None
