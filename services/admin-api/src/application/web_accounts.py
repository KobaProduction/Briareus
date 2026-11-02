"""Create, update and verify account drafts through the existing account service."""

from __future__ import annotations

import asyncio
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import uuid4

from domain.accounts import Account, AccountConflictError, AuthType, Provider
from domain.web_accounts import (
    AccountInputRejected,
    AccountMissing,
    AccountUpdateConflict,
    CandidateVerificationFailed,
    CandidateVerificationTimedOut,
    StaleAccountRevision,
    require_account_revision,
    require_candidate_credential,
    require_same_provider,
    utc_timestamp,
)

from application._accounts_binding import _AccountsBinding


@dataclass(frozen=True, slots=True)
class AccountDraft:
    alias: str
    provider: Provider
    auth_type: AuthType
    base_url: str = ""
    external_id: str = ""
    verify_tls: bool = True
    ca_cert_pem: str = ""
    enabled: bool = True

    def account(self, existing: Account | None = None) -> Account:
        return Account(
            id=existing.id if existing is not None else str(uuid4()),
            alias=self.alias,
            provider=self.provider,
            auth_type=self.auth_type,
            base_url=self.base_url,
            external_id=self.external_id,
            verify_tls=self.verify_tls,
            ca_cert_pem=self.ca_cert_pem,
            enabled=self.enabled,
            created_at=existing.created_at if existing is not None else datetime.now(UTC),
            updated_at=existing.updated_at if existing is not None else datetime.now(UTC),
        )


@dataclass(frozen=True, slots=True)
class CreateAccount:
    draft: AccountDraft
    credential: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class UpdateAccount:
    provider: Provider
    account_id: str
    draft: AccountDraft
    credential: str = field(default="", repr=False)
    expected_updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class VerifyCandidate:
    draft: AccountDraft
    credential: str = field(default="", repr=False)
    account_id: str = ""
    draft_revision: str = ""


@dataclass(frozen=True, slots=True)
class CandidateVerification:
    accepted: bool


@dataclass(frozen=True, slots=True)
class CandidateVerified:
    provider: Provider
    draft_revision: str
    ok: Literal[True] = True


class WebAccountStore(Protocol):
    async def get(
        self,
        selector: str,
        *,
        provider: Provider,
        enabled_only: bool = True,
    ) -> Account: ...

    async def create(self, account: Account, *, credential: str) -> Account: ...

    async def update(
        self,
        account: Account,
        *,
        credential: str = "",
        expected_updated_at: datetime | None = None,
    ) -> Account: ...


class CandidateVerifier(Protocol):
    async def verify(
        self,
        account: Account,
        *,
        credential: str,
        credential_account_id: str,
    ) -> CandidateVerification: ...


class CreateWebAccount(_AccountsBinding[WebAccountStore]):
    async def execute(self, command: CreateAccount) -> Account:
        try:
            return await self._accounts.create(
                command.draft.account(),
                credential=command.credential,
            )
        except (KeyError, ValueError) as exc:
            raise AccountInputRejected(str(exc)) from exc


class UpdateWebAccount(_AccountsBinding[WebAccountStore]):
    async def execute(self, command: UpdateAccount) -> Account:
        require_same_provider(command.provider.value, command.draft.provider.value)
        try:
            existing = await self._accounts.get(
                command.account_id,
                provider=command.provider,
                enabled_only=False,
            )
            require_account_revision(command.expected_updated_at, existing.updated_at)
            return await self._accounts.update(
                command.draft.account(existing),
                credential=command.credential,
                expected_updated_at=(
                    existing.updated_at if command.expected_updated_at is not None else None
                ),
            )
        except KeyError as exc:
            raise AccountMissing(str(exc)) from exc
        except (StaleAccountRevision, AccountConflictError) as exc:
            current = await self._current_updated_at(command)
            raise AccountUpdateConflict(current) from exc
        except ValueError as exc:
            raise AccountInputRejected(str(exc)) from exc

    async def _current_updated_at(self, command: UpdateAccount) -> str | None:
        # This is a separate fresh read after the failed optimistic comparison
        # or save. The failed write's snapshot cannot describe the new revision.
        try:
            current = await self._accounts.get(
                command.account_id,
                provider=command.provider,
                enabled_only=False,
            )
        except KeyError:
            return None
        return utc_timestamp(current.updated_at).isoformat()


class VerifyWebAccountCandidate:
    def __init__(
        self,
        accounts: WebAccountStore,
        verifier: CandidateVerifier,
        slots: AbstractAsyncContextManager[None],
    ) -> None:
        self._accounts = accounts
        self._verifier = verifier
        self._slots = slots

    async def execute(self, command: VerifyCandidate) -> CandidateVerified:
        existing = await self._existing(command)
        try:
            account = command.draft.account(existing)
        except ValueError as exc:
            raise AccountInputRejected(str(exc)) from exc
        require_candidate_credential(command.credential, existing=existing is not None)
        try:
            async with self._slots:
                result = await asyncio.wait_for(
                    self._verifier.verify(
                        account,
                        credential=command.credential,
                        credential_account_id=existing.id if existing is not None else "",
                    ),
                    timeout=20.0,
                )
        except TimeoutError as exc:
            raise CandidateVerificationTimedOut("candidate verification timed out") from exc
        except Exception as exc:
            raise CandidateVerificationFailed("candidate verification failed") from exc
        if result.accepted is not True:
            raise CandidateVerificationFailed("candidate verification failed")
        return CandidateVerified(command.draft.provider, command.draft_revision)

    async def _existing(self, command: VerifyCandidate) -> Account | None:
        if not command.account_id:
            return None
        try:
            return await self._accounts.get(
                command.account_id,
                provider=command.draft.provider,
                enabled_only=False,
            )
        except KeyError as exc:
            raise AccountMissing("account not found") from exc
        except ValueError as exc:
            raise AccountInputRejected(str(exc)) from exc
