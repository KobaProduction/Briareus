"""Durable intent precedes a single, non-idempotent Rauthy creation request."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from projects.application._authority_bindings import _FreshAuthority
from projects.domain.invitations import (
    InvitationCapabilities,
    InvitationEmail,
    InvitationOutcome,
    InvitationResult,
    InviterOutcome,
    ProviderUser,
)
from projects.domain.management import ManagementError


@dataclass(frozen=True, slots=True)
class InvitationActor:
    uuid: UUID
    operator: bool


@dataclass(frozen=True, slots=True)
class InvitationIdentity:
    issuer: str
    subject: str


@dataclass(frozen=True, slots=True)
class SetInviter:
    user_uuid: UUID
    enabled: bool


@dataclass(frozen=True, slots=True)
class IssueInvitation:
    email: InvitationEmail


@dataclass(frozen=True, slots=True)
class InvitationCommand:
    identity: InvitationIdentity
    actor: InvitationActor
    operation_uuid: UUID
    fingerprint: str
    change: SetInviter | IssueInvitation


class InvitationTransaction(Protocol):
    async def capabilities(
        self,
        identity: InvitationIdentity,
        actor: InvitationActor,
    ) -> InvitationCapabilities: ...
    async def lock(self, command: InvitationCommand) -> None: ...
    async def require_actor(self, command: InvitationCommand) -> None: ...
    async def previous(self, command: InvitationCommand) -> InvitationResult | None: ...
    async def set_inviter(
        self, command: InvitationCommand, change: SetInviter
    ) -> InviterOutcome: ...
    async def record_intent(self, command: InvitationCommand, change: IssueInvitation) -> None: ...
    async def finish(self, command: InvitationCommand, user: ProviderUser) -> InvitationOutcome: ...


class InvitationUnitOfWork(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[InvitationTransaction]: ...


class InvitationProvider(Protocol):
    def unavailable_reason(self) -> str | None: ...
    async def lookup(self, email: InvitationEmail) -> int: ...
    async def create(self, email: InvitationEmail) -> ProviderUser: ...


class InvitationAuthority(Protocol):
    async def fresh_expiry(
        self,
        identity: InvitationIdentity,
        actor: InvitationActor,
    ) -> datetime | None: ...


class ManageInvitations(_FreshAuthority):
    def __init__(
        self,
        uow: InvitationUnitOfWork,
        provider: InvitationProvider,
        authority: InvitationAuthority,
        now: Callable[[], datetime],
    ) -> None:
        self._uow = uow
        self._provider = provider
        self._authority = authority
        self._now = now

    async def capabilities(
        self,
        identity: InvitationIdentity,
        actor: InvitationActor,
    ) -> InvitationCapabilities:
        async with self._uow.transaction() as tx:
            current = await tx.capabilities(identity, actor)
        reason = self._provider.unavailable_reason() if current.can_invite else None
        return InvitationCapabilities(
            current.can_invite,
            current.can_manage_inviters,
            current.inviter_ids,
            reason,
        )

    async def execute(
        self,
        command: InvitationCommand,
        deadline: datetime,
    ) -> InvitationResult:
        async with self._uow.transaction() as tx:
            await tx.lock(command)
            await tx.require_actor(command)
            previous = await tx.previous(command)
            if previous is not None:
                return previous
            self._fresh(deadline)
            if isinstance(command.change, SetInviter):
                outcome = await tx.set_inviter(command, command.change)
                self._fresh(deadline)
                return outcome
        return await self._issue(command, deadline)

    async def _issue(
        self,
        command: InvitationCommand,
        deadline: datetime,
    ) -> InvitationResult:
        change = command.change
        if not isinstance(change, IssueInvitation):
            raise ManagementError(422, "COMMAND_INVALID")
        reason = self._provider.unavailable_reason()
        if reason is not None:
            raise ManagementError(503, reason)
        status = await self._provider.lookup(change.email)
        if status == 200:
            raise ManagementError(409, "RAUTHY_ACCOUNT_ALREADY_EXISTS")
        if status != 404:
            raise ManagementError(503, "RAUTHY_USER_LOOKUP_UNAVAILABLE")
        async with self._uow.transaction() as tx:
            await tx.lock(command)
            await tx.require_actor(command)
            previous = await tx.previous(command)
            if previous is not None:
                return previous
            self._fresh(deadline)
            await tx.record_intent(command, change)
        try:
            user = await self._provider.create(change.email)
        except Exception:
            raise ManagementError(503, "INVITATION_OUTCOME_UNCONFIRMED") from None
        fresh_expiry = await self._authority.fresh_expiry(command.identity, command.actor)
        if fresh_expiry is None:
            raise ManagementError(503, "INVITATION_OUTCOME_UNCONFIRMED")
        async with self._uow.transaction() as tx:
            await tx.lock(command)
            try:
                await tx.require_actor(command)
            except ManagementError:
                raise ManagementError(503, "INVITATION_OUTCOME_UNCONFIRMED") from None
            self._fresh(min(deadline, fresh_expiry), "INVITATION_OUTCOME_UNCONFIRMED")
            return await tx.finish(command, user)
