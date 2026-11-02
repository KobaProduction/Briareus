"""Existing provider/Valkey implementations bound to browser identity application ports."""

from pydantic import SecretStr

from control_panel_api._oidc import RauthyOidcAdapter
from control_panel_api.domain.oidc_identity import (
    OidcAuthorizationAttempt,
    PrivateOidcPending,
    VerifiedOidcLogin,
)
from control_panel_api.infrastructure._oidc_bindings import (
    _BrowserSessionDelete,
    _BrowserSessionRead,
)
from control_panel_api.infrastructure.browser_native_transactions import ValkeyNativeTransactions
from control_panel_api.infrastructure.browser_renewal import renew_browser_session
from control_panel_api.infrastructure.browser_store import OidcBrowserSessionStore
from control_panel_api.infrastructure.browser_transactions import ValkeyOidcTransactions


class ProviderBrowserIdentity(_BrowserSessionRead, _BrowserSessionDelete):
    def __init__(
        self, provider: RauthyOidcAdapter, sessions: OidcBrowserSessionStore, *, callback: str
    ) -> None:
        self._provider = provider
        self._sessions = sessions
        self._transactions: ValkeyOidcTransactions = sessions
        self._native_transactions: ValkeyNativeTransactions = sessions
        self._storage = sessions.storage
        self._callback = callback

    async def prepare(self) -> OidcAuthorizationAttempt:
        return await self._provider.prepare_authorization_code(redirect_uri=self._callback)

    async def save(self, attempt: OidcAuthorizationAttempt) -> None:
        await self._transactions.save_transaction(
            state=attempt.state,
            nonce=attempt.nonce,
            verifier=attempt.code_verifier.get_secret_value(),
            issuer=self._provider.issuer,
            client_id=self._provider.client_id,
            resource_audience=attempt.resource_audience,
        )

    async def consume(self, state: str) -> PrivateOidcPending | None:
        return await self._transactions.consume_transaction(
            state=state,
            issuer=self._provider.issuer,
            client_id=self._provider.client_id,
            resource_audience=self._provider.resource_audience,
        )

    async def authenticate(
        self, transaction: PrivateOidcPending, code: str, issuer: str
    ) -> VerifiedOidcLogin:
        return await self._provider.authenticate_authorization_code(
            code=code,
            redirect_uri=self._callback,
            code_verifier=SecretStr(transaction.verifier.get_secret_value()),
            expected_nonce=transaction.nonce,
            expected_issuer=issuer,
            resource_audience=transaction.resource_audience,
        )

    async def create(self, login: VerifiedOidcLogin) -> tuple[str, int]:
        return await self._sessions.create_session(
            login.identity,
            resource=login.resource,
            refresh=login.refresh,
        )

    async def renew(self, ticket: str) -> int | None:
        return await renew_browser_session(self._storage, ticket, self._provider)

    identity = _BrowserSessionRead._session

    async def delete_native(self, state: str) -> None:
        await self._native_transactions.delete_native_init(state=state)
