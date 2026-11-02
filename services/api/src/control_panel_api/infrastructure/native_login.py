"""Pinned provider and private Valkey adapters for native login ports."""

from urllib.parse import parse_qs, urlsplit

from pydantic import SecretStr

from control_panel_api._native_credentials import NativeFirstFactorRequest
from control_panel_api._oidc import RauthyOidcAdapter
from control_panel_api._rauthy_native_init import PinnedNativeRauthyInit
from control_panel_api.application.native_login import OtpStarted
from control_panel_api.application.native_login_start import NativeAttempt, ProviderInit
from control_panel_api.domain.native_login import (
    NativeCredentials,
    NativeProviderProtocolUnavailable,
    PrivateNativeLoginStep,
    PrivateNativeOtpPending,
    PrivateNativePending,
    SecretText,
)
from control_panel_api.domain.oidc_identity import VerifiedOidcLogin
from control_panel_api.infrastructure._oidc_bindings import _NativePow
from control_panel_api.infrastructure.browser_native_transactions import ValkeyNativeTransactions
from control_panel_api.infrastructure.browser_sessions import ValkeyBrowserSessions
from control_panel_api.infrastructure.browser_store import OidcBrowserSessionStore


class ProviderNativeLogin(_NativePow):
    def __init__(
        self,
        provider: RauthyOidcAdapter,
        transactions: OidcBrowserSessionStore,
        native: PinnedNativeRauthyInit,
        *,
        callback: str,
    ) -> None:
        self._provider = provider
        self._transactions: ValkeyNativeTransactions = transactions
        self._sessions: ValkeyBrowserSessions = transactions
        self._native = native
        self._callback = callback

    async def claim(self, state: str) -> PrivateNativePending | None:
        return await self._transactions.consume_native_init(
            state=state, issuer=self._provider.issuer, client_id=self._provider.client_id
        )

    async def claim_current(self, pending: PrivateNativePending) -> bool:
        return await self._transactions.native_claim_is_current(pending)

    async def delete(self, state: str) -> None:
        await self._transactions.delete_native_init(state=state)

    async def prepare(self) -> NativeAttempt:
        attempt = await self._provider.prepare_authorization_code(redirect_uri=self._callback)
        return NativeAttempt(
            attempt.state,
            attempt.nonce,
            attempt.code_verifier,
            attempt.resource_audience,
            attempt.expires_at,
        )

    async def initialize(self) -> ProviderInit:
        init = await self._native.initialize()
        return ProviderInit(init.csrf_token, init.provider_cookie_header, init.expires_at)

    async def save(self, attempt: NativeAttempt, init: ProviderInit, seconds: int) -> None:
        await self._transactions.save_native_init(
            state=attempt.state,
            nonce=attempt.nonce,
            verifier=attempt.verifier.get_secret_value(),
            issuer=self._provider.issuer,
            client_id=self._provider.client_id,
            csrf=SecretStr(init.csrf.get_secret_value()),
            provider_cookie=SecretStr(init.cookie.get_secret_value()),
            seconds=seconds,
            resource_audience=attempt.resource_audience,
        )

    async def current(self, state: str) -> bool:
        return await self._transactions.native_init_is_current(
            state=state, issuer=self._provider.issuer, client_id=self._provider.client_id
        )

    async def reserve_pow(self, state: str) -> bool:
        return await self._transactions.reserve_native_pow(
            state=state, issuer=self._provider.issuer, client_id=self._provider.client_id
        )

    async def confirm_pow(self, state: str) -> bool:
        return await self._transactions.confirm_native_pow(
            state=state, issuer=self._provider.issuer, client_id=self._provider.client_id
        )

    async def authorize(
        self, pending: PrivateNativePending, credentials: NativeCredentials
    ) -> PrivateNativeLoginStep:
        boundary = NativeFirstFactorRequest(
            email=SecretStr(credentials.email.get_secret_value()),
            password=SecretStr(credentials.password.get_secret_value()),
            pow=SecretStr(credentials.pow.get_secret_value()),
        )
        return await self._native.authorize(pending=pending, credentials=boundary)

    async def stage_otp(self, pending: PrivateNativePending, step: PrivateNativeLoginStep) -> bool:
        if step.secret is None or step.provider_cookie is None or step.csrf_token is None:
            raise NativeProviderProtocolUnavailable("private OTP challenge unavailable")
        return await self._transactions.stage_native_otp(
            pending=pending,
            login_code=SecretStr(step.secret.get_secret_value()),
            methods=tuple(
                (kind, SecretStr(secret.get_secret_value()))
                for kind, secret in step.available_otp_methods()
            ),
            provider_cookie=SecretStr(step.provider_cookie.get_secret_value()),
            csrf_token=SecretStr(step.csrf_token.get_secret_value()),
        )

    async def authenticate(
        self, pending: PrivateNativePending, callback: SecretText
    ) -> VerifiedOidcLogin:
        # The pinned wire decoder has already verified exact callback/code/state/iss.
        args = parse_qs(urlsplit(callback.get_secret_value()).query, strict_parsing=True)
        return await self._provider.authenticate_authorization_code(
            code=args["code"][0],
            redirect_uri=self._callback,
            code_verifier=SecretStr(pending.verifier.get_secret_value()),
            expected_nonce=pending.nonce,
            expected_issuer=args["iss"][0],
            resource_audience=pending.resource_audience,
        )

    async def complete(
        self, pending: PrivateNativePending, login: VerifiedOidcLogin
    ) -> tuple[str, int] | None:
        return await self._transactions.complete_native_login(
            pending=pending, identity=login.identity, resource=login.resource, refresh=login.refresh
        )

    async def session_exists(self, ticket: str) -> bool:
        return await self._sessions.get_session(ticket) is not None

    async def claim_otp_start(
        self, state: str, method_index: int
    ) -> PrivateNativeOtpPending | None:
        return await self._transactions.claim_native_otp_start(
            state=state,
            issuer=self._provider.issuer,
            client_id=self._provider.client_id,
            method_index=method_index,
        )

    async def start_otp(self, challenge: PrivateNativeOtpPending) -> OtpStarted:
        result, cookie, csrf = await self._native.otp_start(pending=challenge)
        return OtpStarted(result.secret, result.expires_at, cookie, csrf)

    async def confirm_otp(self, challenge: PrivateNativeOtpPending, started: OtpStarted) -> bool:
        return await self._transactions.confirm_native_otp_start(
            challenge=challenge,
            otp_code=SecretStr(started.secret.get_secret_value()),
            otp_expires_at=started.expires_at,
            provider_cookie=SecretStr(started.provider_cookie.get_secret_value()),
            csrf_token=SecretStr(started.csrf_token.get_secret_value()),
        )

    async def claim_otp_finish(self, state: str) -> PrivateNativeOtpPending | None:
        return await self._transactions.claim_native_otp_finish(
            state=state, issuer=self._provider.issuer, client_id=self._provider.client_id
        )

    async def finish_otp(
        self, challenge: PrivateNativeOtpPending, value: str
    ) -> PrivateNativeLoginStep:
        return await self._native.otp_finish(pending=challenge, otp_value=value)
