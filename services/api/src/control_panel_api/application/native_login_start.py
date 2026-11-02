"""Allocate native init and one-use provider PoW without browser navigation."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from control_panel_api.domain.native_login import (
    NativeLoginResult,
    NativeProviderProtocolUnavailable,
    SecretText,
    login_failure,
)
from control_panel_api.domain.oidc_identity import (
    OidcProviderUnavailable,
    OidcSessionStoreUnavailable,
)


@dataclass(frozen=True, slots=True)
class NativeAttempt:
    state: str
    nonce: str
    verifier: SecretText = field(repr=False)
    resource_audience: str | None
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ProviderInit:
    csrf: SecretText = field(repr=False)
    cookie: SecretText = field(repr=False)
    expires_at: datetime


class NativeInitiationPort(Protocol):
    async def delete(self, state: str) -> None: ...
    async def prepare(self) -> NativeAttempt: ...
    async def initialize(self) -> ProviderInit: ...
    async def save(self, attempt: NativeAttempt, init: ProviderInit, seconds: int) -> None: ...
    async def current(self, state: str) -> bool: ...
    async def reserve_pow(self, state: str) -> bool: ...
    async def issue_pow(self) -> str: ...
    async def confirm_pow(self, state: str) -> bool: ...


class NativeLoginStart:
    def __init__(self, port: NativeInitiationPort) -> None:
        self._port = port

    async def start(self, prior: str | None) -> NativeLoginResult:
        try:
            if prior is not None:
                await self._port.delete(prior)
            attempt = await self._port.prepare()
            init = await self._port.initialize()
            now = datetime.now(UTC)
            seconds = min(
                300,
                int((attempt.expires_at - now).total_seconds()),
                int((init.expires_at - now).total_seconds()),
            )
            if seconds < 1:
                raise NativeProviderProtocolUnavailable("Rauthy native Init expired")
            await self._port.save(attempt, init, seconds)
        except (
            OidcProviderUnavailable,
            NativeProviderProtocolUnavailable,
            OidcSessionStoreUnavailable,
        ):
            return login_failure(503, "NATIVE_INIT_UNAVAILABLE")
        return NativeLoginResult(
            201, "first_factor_required", ticket=attempt.state, expires_in=seconds
        )

    async def issue_pow(self, state: str) -> NativeLoginResult:
        try:
            if not await self._port.current(state):
                return login_failure(401, "NATIVE_INIT_EXPIRED")
            if not await self._port.reserve_pow(state):
                return login_failure(409, "NATIVE_POW_ALREADY_RESERVED")
            challenge = await self._port.issue_pow()
            if not await self._port.confirm_pow(state):
                return login_failure(401, "NATIVE_INIT_EXPIRED")
        except (OidcSessionStoreUnavailable, NativeProviderProtocolUnavailable):
            return login_failure(503, "NATIVE_POW_UNAVAILABLE")
        return NativeLoginResult(200, challenge=challenge)
