"""Identity and all private resource bearers share one revocable Valkey record."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from pydantic import SecretStr
from valkey.exceptions import ValkeyError

from control_panel_api._oidc_origin_policy import validate_files_resource_intent
from control_panel_api.domain.oidc_identity import (
    OidcSessionStoreUnavailable,
    PrivateOidcResourceCredential,
    VerifiedOidcIdentity,
    VerifiedRefreshCredential,
)
from control_panel_api.domain.platform_authority import PanelOidcSession
from control_panel_api.infrastructure.browser_records import (
    StoredBrowserSession,
    browser_record,
)
from control_panel_api.infrastructure.browser_session_preparation import prepare_browser_session
from control_panel_api.infrastructure.browser_storage import BrowserStorageContext


class ValkeyBrowserSessions:
    def __init__(self, storage: BrowserStorageContext) -> None:
        self._storage = storage

    async def create_session(
        self,
        identity: VerifiedOidcIdentity,
        *,
        resource: PrivateOidcResourceCredential | None = None,
        refresh: VerifiedRefreshCredential | None = None,
    ) -> tuple[str, int]:
        prepared = prepare_browser_session(identity, resource=resource, refresh=refresh)
        try:
            created = await self._storage.client.set(
                self._storage.key("session", prepared.ticket),
                json.dumps(
                    prepared.record.model_dump(mode="json", exclude_unset=True, exclude_none=True),
                    separators=(",", ":"),
                ),
                ex=prepared.seconds,
                nx=True,
            )
        except ValkeyError as exc:
            raise OidcSessionStoreUnavailable("OIDC session store unavailable") from exc
        if not created:
            raise OidcSessionStoreUnavailable("OIDC session collision")
        return prepared.ticket, prepared.seconds

    async def get_session(self, ticket: str) -> PanelOidcSession | None:
        try:
            raw = await self._storage.client.get(self._storage.key("session", ticket))
        except ValkeyError as exc:
            raise OidcSessionStoreUnavailable("OIDC session store unavailable") from exc
        if raw is None or not isinstance(raw, str) or len(raw) > 98304:
            return None
        try:
            item = browser_record(raw, StoredBrowserSession)
            if (
                not item.subject
                or item.expires_at.tzinfo is None
                or item.expires_at <= datetime.now(UTC)
            ):
                return None
            return PanelOidcSession(item.issuer, item.subject, item.client_id, item.expires_at)
        except (ValueError, TypeError, KeyError):
            return None

    async def get_resource_credential(
        self, ticket: str, *, issuer: str, client_id: str, audience: str
    ) -> PrivateOidcResourceCredential | None:
        """Fetch private escrow only, never treat it as a current effect decision.

        Identity and bearer share ONE revocable Valkey record. Logout cannot
        delete the identity yet leave a separately reusable bearer record.
        """
        validate_files_resource_intent(
            issuer=issuer, client_id=client_id, resource_audience=audience
        )
        try:
            raw = await self._storage.client.get(self._storage.key("session", ticket))
        except ValkeyError:
            raise OidcSessionStoreUnavailable("private resource escrow unavailable") from None
        if not isinstance(raw, str) or len(raw) > 98304:
            return None
        try:
            value = browser_record(raw, StoredBrowserSession)
            resource = value.resource
            if resource is None:
                return None
            expiry = min(value.expires_at, resource.expires_at)
            bearer = resource.bearer
            if (
                value.issuer.rstrip("/") != issuer.rstrip("/")
                or value.client_id != client_id
                or resource.audience != audience
                or not 1 <= len(value.subject) <= 256
                or expiry.tzinfo is None
                or expiry <= datetime.now(UTC)
                or not 80 <= len(bearer) <= 8192
                or not bearer.isascii()
                or any(char.isspace() for char in bearer)
            ):
                return None
            return PrivateOidcResourceCredential(
                value.issuer, value.subject, client_id, audience, expiry, SecretStr(bearer)
            )
        except (ValueError, TypeError, KeyError, AttributeError):
            return None

    async def delete_session(self, ticket: str) -> None:
        try:
            await self._storage.client.delete(self._storage.key("session", ticket))
        except ValkeyError as exc:
            raise OidcSessionStoreUnavailable("OIDC logout could not be committed") from exc
