"""Legacy invitation issue and revoke scenarios with owner transaction ports."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from common.platform_errors import AccessDenied, Conflict, ResourceMissing
from identity._domain import UserRole
from identity.domain.invitations import (
    InvitationAlreadyUsed,
    InvitationPermissionDenied,
    RevocableInvitation,
)


@dataclass(frozen=True)
class InvitationActor:
    enabled: bool
    role: UserRole
    credential_version: int


@dataclass(frozen=True)
class PendingInvitation:
    kind: str
    token_digest: str
    issuer_id: UUID
    expires_at: datetime
    target_id: UUID | None = None


@dataclass(frozen=True)
class IssuedInvitationReceipt:
    invitation_id: UUID


class InvitationTransaction(Protocol):
    async def user(self, user_id: UUID) -> InvitationActor | None: ...

    def issue(self, invitation: PendingInvitation) -> IssuedInvitationReceipt: ...

    async def lock_invitation(self, invitation_id: UUID) -> RevocableInvitation | None: ...

    def revoke(self, now: datetime) -> None: ...

    def record(self, actor_id: UUID, target_id: UUID, event: str, revision: int) -> None: ...


class InvitationTransactions(Protocol):
    def __call__(self) -> AbstractAsyncContextManager[InvitationTransaction]: ...


class InvitationSecrets(Protocol):
    def random_token(self) -> str: ...

    def token_digest(self, token: str) -> str: ...


class InvitationLinks(Protocol):
    def link(self, kind: str, raw: str) -> str: ...


@dataclass(frozen=True)
class LegacyIdentityInvitations:
    transactions: InvitationTransactions
    secrets: InvitationSecrets
    links: InvitationLinks
    now: Callable[[], datetime]

    async def issue_registration(self, actor: UUID) -> str:
        async with self.transactions() as tx:
            issuer = await tx.user(actor)
            if issuer is None or not issuer.enabled:
                raise AccessDenied("current user is not active")
            raw = self.secrets.random_token()
            link = self.links.link("invite", raw)
            receipt = tx.issue(
                PendingInvitation(
                    "registration",
                    self.secrets.token_digest(raw),
                    actor,
                    self.now() + timedelta(days=7),
                )
            )
            tx.record(
                actor,
                receipt.invitation_id,
                "identity.invitation_issued",
                issuer.credential_version,
            )
        return link

    async def issue_password_reset(self, admin: UUID, target: UUID) -> str:
        async with self.transactions() as tx:
            actor = await tx.user(admin)
            user = await tx.user(target)
            if actor is None or not actor.enabled or actor.role != "superuser":
                raise AccessDenied("active superuser required")
            if user is None or not user.enabled:
                raise ResourceMissing("target user not found")
            raw = self.secrets.random_token()
            link = self.links.link("reset", raw)
            tx.issue(
                PendingInvitation(
                    "password_reset",
                    self.secrets.token_digest(raw),
                    admin,
                    self.now() + timedelta(minutes=15),
                    target,
                )
            )
            tx.record(admin, target, "identity.password_reset_issued", user.credential_version)
        return link

    async def revoke(self, actor: UUID, invitation_id: UUID) -> None:
        async with self.transactions() as tx:
            user = await tx.user(actor)
            if user is None or not user.enabled:
                raise AccessDenied("active user required")
            invitation = await tx.lock_invitation(invitation_id)
            if invitation is None:
                raise ResourceMissing("invitation not found")
            try:
                required = invitation.require_revocation(actor, superuser=user.role == "superuser")
            except InvitationPermissionDenied as exc:
                raise AccessDenied(str(exc)) from exc
            except InvitationAlreadyUsed as exc:
                raise Conflict(str(exc)) from exc
            if required:
                tx.revoke(self.now())
                tx.record(
                    actor, invitation_id, "identity.invitation_revoked", user.credential_version
                )
