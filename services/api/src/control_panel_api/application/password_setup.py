"""Coordinate current Rauthy challenges and atomic browser preparation claims."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from pydantic import BaseModel, ConfigDict, StrictInt

from control_panel_api.domain.native_login import SecretText
from control_panel_api.domain.password_setup import (
    PasswordPreparation,
    PasswordSetupDenied,
    PasswordSetupUnavailable,
    require_password_envelope,
    require_recovery_envelope,
    require_setup_code,
)


class ProviderPasswordPolicy(BaseModel):
    """Rauthy v0.37.1 PasswordPolicy metadata; the provider alone evaluates passwords.

    Source: sebadob/rauthy ce35a70, src/data/src/entity/password.rs.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
    length_min: StrictInt | None = None
    length_max: StrictInt | None = None
    include_lower_case: StrictInt | None = None
    include_upper_case: StrictInt | None = None
    include_digits: StrictInt | None = None
    include_special: StrictInt | None = None
    valid_days: StrictInt | None = None
    not_recently_used: StrictInt | None = None


@dataclass(frozen=True, slots=True)
class PreparedProviderReset:
    csrf: SecretText = field(repr=False)
    cookie: SecretText = field(repr=False)
    age: int
    policy: ProviderPasswordPolicy


@dataclass(frozen=True, slots=True)
class PasswordSetupPrepared:
    ticket: str = field(repr=False)
    age: int
    policy: ProviderPasswordPolicy


class PasswordSetupStore(Protocol):
    async def peek(self, ticket: str) -> PasswordPreparation | None: ...
    async def claim(self, ticket: str) -> PasswordPreparation | None: ...
    async def save(self, ticket: str, preparation: PasswordPreparation, age: int) -> bool: ...
    async def delete(self, ticket: str) -> None: ...


class PasswordSetupProvider(Protocol):
    async def issue_pow(self) -> str: ...
    async def request_recovery(self, email: str, pow_solution: SecretText) -> bool: ...
    async def prepare(
        self, user_id: str, code: SecretText, prior_cookie: SecretText | None
    ) -> PreparedProviderReset | None: ...
    async def finish(self, preparation: PasswordPreparation, password: SecretText) -> bool: ...


class PasswordSetup:
    def __init__(
        self,
        provider: PasswordSetupProvider,
        store: PasswordSetupStore,
        *,
        mail_ready: Callable[[], bool],
        now: Callable[[], float],
        ticket: Callable[[], str],
    ) -> None:
        self._provider = provider
        self._store = store
        self._mail_ready = mail_ready
        self._now = now
        self._ticket = ticket

    def _require_mail(self) -> None:
        if not self._mail_ready():
            raise PasswordSetupDenied(503, "RAUTHY_INVITATION_MAIL_UNCONFIGURED")

    async def recovery_pow(self) -> str:
        self._require_mail()
        return await self._provider.issue_pow()

    async def request_recovery(self, email: str, pow_solution: SecretText) -> None:
        self._require_mail()
        require_recovery_envelope(email, pow_solution)
        if not await self._provider.request_recovery(email, pow_solution):
            raise PasswordSetupDenied(400, "RECOVERY_PROVIDER_REJECTED")

    async def prepare(
        self,
        user_id: str,
        code: SecretText,
        prior_ticket: str | None,
    ) -> PasswordSetupPrepared:
        require_setup_code(code)
        prior = await self._store.peek(prior_ticket) if prior_ticket else None
        cookie = prior.cookie if prior is not None and prior.matches(user_id, code) else None
        prepared = await self._provider.prepare(user_id, code, cookie)
        if prepared is None:
            raise PasswordSetupDenied(400, "SETUP_CODE_INVALID_OR_EXPIRED")
        ticket = self._ticket()
        private = PasswordPreparation(
            user_id, code, prepared.csrf, prepared.cookie, self._now() + prepared.age
        )
        if not await self._store.save(ticket, private, prepared.age):
            raise PasswordSetupUnavailable
        if prior_ticket:
            await self._store.delete(prior_ticket)
        return PasswordSetupPrepared(ticket, prepared.age, prepared.policy)

    async def finish(self, ticket: str | None, password: SecretText) -> None:
        require_password_envelope(password)
        if not ticket:
            raise PasswordSetupDenied(401, "SETUP_PREPARATION_REQUIRED")
        private = await self._store.claim(ticket)
        if private is None:
            raise PasswordSetupDenied(401, "SETUP_PREPARATION_EXPIRED")
        # Claim before submission: ambiguous provider results must never auto-retry.
        if await self._provider.finish(private, password):
            return
        remaining = private.remaining(self._now())
        if remaining > 0:
            await self._store.save(ticket, private, remaining)
        raise PasswordSetupDenied(400, "SETUP_PROVIDER_REJECTED")
