"""One-use native login, MFA and cancellation independent of HTTP and storage."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Protocol

from control_panel_api.domain.native_login import (
    NativeCredentials,
    NativeLoginResult,
    NativeProviderProtocolUnavailable,
    PrivateNativeLoginStep,
    PrivateNativeOtpPending,
    PrivateNativePending,
    SecretText,
    login_failure,
)
from control_panel_api.domain.oidc_identity import (
    OidcIdentityKeysUnavailable,
    OidcIdentityRejected,
    OidcProviderUnavailable,
    OidcSessionStoreUnavailable,
    VerifiedOidcLogin,
)


class ConnectionStatus(Protocol):
    async def is_disconnected(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class OtpStarted:
    secret: SecretText = field(repr=False)
    expires_at: int
    provider_cookie: SecretText = field(repr=False)
    csrf_token: SecretText = field(repr=False)


class NativeLoginPort(Protocol):
    async def claim(self, state: str) -> PrivateNativePending | None: ...
    async def claim_current(self, pending: PrivateNativePending) -> bool: ...
    async def delete(self, state: str) -> None: ...
    async def authorize(
        self, pending: PrivateNativePending, credentials: NativeCredentials
    ) -> PrivateNativeLoginStep: ...
    async def stage_otp(
        self, pending: PrivateNativePending, step: PrivateNativeLoginStep
    ) -> bool: ...
    async def authenticate(
        self, pending: PrivateNativePending, callback: SecretText
    ) -> VerifiedOidcLogin: ...
    async def complete(
        self, pending: PrivateNativePending, login: VerifiedOidcLogin
    ) -> tuple[str, int] | None: ...
    async def session_exists(self, ticket: str) -> bool: ...
    async def claim_otp_start(
        self, state: str, method_index: int
    ) -> PrivateNativeOtpPending | None: ...
    async def start_otp(self, challenge: PrivateNativeOtpPending) -> OtpStarted: ...
    async def confirm_otp(
        self, challenge: PrivateNativeOtpPending, started: OtpStarted
    ) -> bool: ...
    async def claim_otp_finish(self, state: str) -> PrivateNativeOtpPending | None: ...
    async def finish_otp(
        self, challenge: PrivateNativeOtpPending, value: str
    ) -> PrivateNativeLoginStep: ...


class NativeLogin:
    def __init__(self, port: NativeLoginPort, *, resource_audience: str | None) -> None:
        self._port = port
        self._resource_audience = resource_audience

    async def retire(self, state: str) -> bool:
        """Drain bounded cancellation even if downstream cancellation repeats."""

        async def remove() -> None:
            async with asyncio.timeout(4):
                await self._port.delete(state)

        task = asyncio.create_task(remove())
        interrupted = False
        try:
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    interrupted = True
            task.result()
        except (OidcSessionStoreUnavailable, TimeoutError):
            if interrupted:
                raise asyncio.CancelledError from None
            return False
        if interrupted:
            raise asyncio.CancelledError
        return True

    async def _current(self, pending: PrivateNativePending, connection: ConnectionStatus) -> bool:
        return (
            pending.resource_audience == self._resource_audience
            and await self._port.claim_current(pending)
            and not await connection.is_disconnected()
        )

    async def _stage_otp(
        self,
        pending: PrivateNativePending,
        step: PrivateNativeLoginStep,
        connection: ConnectionStatus,
    ) -> NativeLoginResult:
        methods = step.available_otp_methods()
        if not methods:
            return NativeLoginResult(409, "otp_pending", restart_required=True)
        if step.secret is None or step.provider_cookie is None or step.csrf_token is None:
            raise NativeProviderProtocolUnavailable("private OTP challenge unavailable")
        stored = await self._port.stage_otp(pending, step)
        if not stored or await connection.is_disconnected():
            return login_failure(401, "NATIVE_ATTEMPT_EXPIRED_OR_CANCELLED")
        return NativeLoginResult(
            202,
            "otp_pending",
            continuation_available=True,
            methods=tuple(kind for kind, _secret in methods),
        )

    async def _complete(
        self,
        pending: PrivateNativePending,
        step: PrivateNativeLoginStep,
        connection: ConnectionStatus,
    ) -> NativeLoginResult:
        if step.state != "oauth_callback_pending" or step.secret is None:
            raise NativeProviderProtocolUnavailable("native step cannot finish login")
        login = await self._port.authenticate(pending, step.secret)
        if await connection.is_disconnected():
            return login_failure(401, "NATIVE_ATTEMPT_DISCONNECTED")
        committed = await self._port.complete(pending, login)
        if committed is None:
            return login_failure(401, "NATIVE_ATTEMPT_EXPIRED_OR_CANCELLED")
        ticket, seconds = committed
        if not await self._port.session_exists(ticket) or await connection.is_disconnected():
            return login_failure(401, "NATIVE_ATTEMPT_EXPIRED_OR_CANCELLED")
        return NativeLoginResult(200, "authenticated", ticket=ticket, session_seconds=seconds)

    async def _finish(
        self,
        pending: PrivateNativePending,
        step: PrivateNativeLoginStep,
        connection: ConnectionStatus,
    ) -> NativeLoginResult:
        if step.requires_restart:
            return NativeLoginResult(409, step.state, restart_required=True)
        if step.state == "otp_pending":
            return await self._stage_otp(pending, step, connection)
        if step.state == "rate_limited":
            return NativeLoginResult(
                429, error_code="NATIVE_RATE_LIMITED", retry_not_before=step.retry_not_before
            )
        if step.state == "credentials_rejected":
            return login_failure(401, "NATIVE_PROVIDER_AUTH_REJECTED")
        if step.state == "request_rejected":
            return login_failure(400, "NATIVE_PROVIDER_REQUEST_REJECTED")
        if step.state == "provider_access_denied":
            return login_failure(403, "NATIVE_PROVIDER_ACCESS_DENIED")
        return await self._complete(pending, step, connection)

    async def _retire_failed(self, state: str, result: NativeLoginResult) -> NativeLoginResult:
        if not result.preserves_claim and not await self.retire(state):
            return login_failure(503, "NATIVE_CANCEL_UNAVAILABLE")
        return result

    async def _first_factor(
        self,
        pending: PrivateNativePending,
        credentials: NativeCredentials,
        connection: ConnectionStatus,
    ) -> NativeLoginResult:
        if not await self._current(pending, connection):
            return login_failure(401, "NATIVE_ATTEMPT_EXPIRED_OR_CANCELLED")
        step = await self._port.authorize(pending, credentials)
        if not await self._current(pending, connection):
            return login_failure(401, "NATIVE_ATTEMPT_EXPIRED_OR_CANCELLED")
        return await self._finish(pending, step, connection)

    async def first_factor(
        self, state: str, credentials: NativeCredentials, connection: ConnectionStatus
    ) -> NativeLoginResult:
        claimed = False
        try:
            async with asyncio.timeout(30):
                pending = await self._port.claim(state)
                if pending is None:
                    return login_failure(401, "NATIVE_ATTEMPT_EXPIRED_OR_CLAIMED")
                claimed = True
                result = await self._first_factor(pending, credentials, connection)
        except asyncio.CancelledError:
            await self.retire(state)
            raise
        except OidcIdentityRejected:
            result = login_failure(401, "NATIVE_IDENTITY_REJECTED")
        except (
            OidcProviderUnavailable,
            OidcIdentityKeysUnavailable,
            OidcSessionStoreUnavailable,
            NativeProviderProtocolUnavailable,
            TimeoutError,
        ):
            claimed = True  # A timed-out claim may already have committed.
            result = login_failure(503, "NATIVE_LOGIN_UNAVAILABLE")
        return await self._retire_failed(state, result) if claimed else result

    async def _start_otp(
        self, challenge: PrivateNativeOtpPending, connection: ConnectionStatus
    ) -> NativeLoginResult:
        if await connection.is_disconnected():
            return login_failure(401, "NATIVE_ATTEMPT_EXPIRED_OR_CANCELLED")
        started = await self._port.start_otp(challenge)
        confirmed = await self._port.confirm_otp(challenge, started)
        if not confirmed or await connection.is_disconnected():
            return login_failure(401, "NATIVE_ATTEMPT_EXPIRED_OR_CANCELLED")
        return NativeLoginResult(
            202,
            "otp_code_pending",
            expires_at=min(started.expires_at, int(challenge.original.expires_at.timestamp())),
        )

    async def otp_start(
        self, state: str, method_index: int, connection: ConnectionStatus
    ) -> NativeLoginResult:
        try:
            challenge = await self._port.claim_otp_start(state, method_index)
        except OidcSessionStoreUnavailable:
            return login_failure(503, "NATIVE_OTP_START_UNAVAILABLE")
        if challenge is None:
            return login_failure(409, "NATIVE_OTP_START_ALREADY_CLAIMED")
        try:
            async with asyncio.timeout(18):
                result = await self._start_otp(challenge, connection)
        except asyncio.CancelledError:
            await self.retire(state)
            raise
        except (NativeProviderProtocolUnavailable, OidcSessionStoreUnavailable, TimeoutError):
            result = login_failure(503, "NATIVE_OTP_START_UNAVAILABLE")
        return await self._retire_failed(state, result)

    async def _finish_otp(
        self, challenge: PrivateNativeOtpPending, value: str, connection: ConnectionStatus
    ) -> NativeLoginResult:
        if await connection.is_disconnected():
            return login_failure(401, "NATIVE_ATTEMPT_EXPIRED_OR_CANCELLED")
        step = await self._port.finish_otp(challenge, value)
        if not await self._port.claim_current(challenge.original):
            return login_failure(401, "NATIVE_ATTEMPT_EXPIRED_OR_CANCELLED")
        return await self._finish(challenge.original, step, connection)

    async def otp_finish(
        self, state: str, value: str, connection: ConnectionStatus
    ) -> NativeLoginResult:
        try:
            challenge = await self._port.claim_otp_finish(state)
        except OidcSessionStoreUnavailable:
            return login_failure(503, "NATIVE_OTP_FINISH_UNAVAILABLE")
        if challenge is None:
            return login_failure(409, "NATIVE_OTP_FINISH_ALREADY_CLAIMED")
        try:
            async with asyncio.timeout(30):
                result = await self._finish_otp(challenge, value, connection)
        except asyncio.CancelledError:
            await self.retire(state)
            raise
        except OidcIdentityRejected:
            result = login_failure(401, "NATIVE_IDENTITY_REJECTED")
        except (
            NativeProviderProtocolUnavailable,
            OidcSessionStoreUnavailable,
            OidcProviderUnavailable,
            OidcIdentityKeysUnavailable,
            TimeoutError,
        ):
            result = login_failure(503, "NATIVE_OTP_FINISH_UNAVAILABLE")
        # OTP finish must yield a signed identity; another MFA step cannot retain its claim.
        if result.status == 202:
            if not await self.retire(state):
                return login_failure(503, "NATIVE_CANCEL_UNAVAILABLE")
            return result
        return await self._retire_failed(state, result)
