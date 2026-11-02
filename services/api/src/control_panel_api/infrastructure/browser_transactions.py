"""Single-use authorization-code transaction persistence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pydantic import SecretStr
from valkey.exceptions import ValkeyError

from control_panel_api._oidc_origin_policy import validate_files_resource_intent
from control_panel_api.domain.oidc_identity import (
    OidcSessionStoreUnavailable,
    PrivateOidcPending,
)
from control_panel_api.infrastructure.browser_records import (
    StoredTransaction,
    browser_record,
)
from control_panel_api.infrastructure.browser_storage import BrowserStorageContext
from control_panel_api.infrastructure.browser_write_records import (
    OidcTransactionWrite,
    encode_browser_write,
)

_MAX_TRANSACTION_SECONDS = 300


class ValkeyOidcTransactions:
    def __init__(self, storage: BrowserStorageContext) -> None:
        self._storage = storage

    async def save_transaction(
        self,
        *,
        state: str,
        nonce: str,
        verifier: str,
        issuer: str,
        client_id: str,
        resource_audience: str | None = None,
    ) -> None:
        validate_files_resource_intent(
            issuer=issuer, client_id=client_id, resource_audience=resource_audience
        )
        key = self._storage.key("transaction", state)
        payload = OidcTransactionWrite(
            nonce=nonce,
            verifier=verifier,
            issuer=issuer,
            client_id=client_id,
            resource_audience=resource_audience,
            expires_at=(
                datetime.now(UTC) + timedelta(seconds=_MAX_TRANSACTION_SECONDS)
            ).isoformat(),
        )
        try:
            created = await self._storage.client.set(
                key,
                encode_browser_write(payload),
                ex=_MAX_TRANSACTION_SECONDS,
                nx=True,
            )
        except ValkeyError as exc:
            raise OidcSessionStoreUnavailable("OIDC transaction store unavailable") from exc
        if not created:
            raise OidcSessionStoreUnavailable("OIDC transaction collision")

    async def consume_transaction(
        self, *, state: str, issuer: str, client_id: str, resource_audience: str | None
    ) -> PrivateOidcPending | None:
        try:
            raw = await self._storage.client.getdel(self._storage.key("transaction", state))
        except ValkeyError as exc:
            raise OidcSessionStoreUnavailable("OIDC transaction store unavailable") from exc
        if raw is None or not isinstance(raw, str) or len(raw) > 16384:
            return None
        try:
            value = browser_record(raw, StoredTransaction)
            if (
                (value.issuer, value.client_id, value.resource_audience)
                != (issuer, client_id, resource_audience)
                or value.expires_at.tzinfo is None
                or value.expires_at <= datetime.now(UTC)
            ):
                return None
            return PrivateOidcPending(
                value.nonce,
                SecretStr(value.verifier),
                issuer,
                client_id,
                resource_audience,
                value.expires_at,
            )
        except (ValueError, TypeError, KeyError):
            return None
