"""Provision only the exact independently verified issuer/subject on ingress."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Protocol
from uuid import UUID

from projects.domain.membership import CurrentRauthyUserLink, PlatformSubjectLinkUnavailable
from projects.domain.user_links import (
    PlatformUserLink,
    ProvisioningAction,
    VerifiedRauthyUserStatus,
    verify_status,
)


class TrustedRauthyUserStatusPort(Protocol):
    async def current_status(self, *, issuer: str, subject: str) -> VerifiedRauthyUserStatus: ...


class UserLinkTransaction(Protocol):
    async def lock_subject(self, issuer: str, subject: str) -> None: ...
    async def get(self, issuer: str, subject: str) -> PlatformUserLink | None: ...
    async def save(
        self,
        link: PlatformUserLink,
        operation_uuid: UUID,
        action: ProvisioningAction,
    ) -> None: ...


class UserLinkUnitOfWork(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[UserLinkTransaction]: ...


class ProvisionCurrentSubject:
    def __init__(
        self,
        status: TrustedRauthyUserStatusPort,
        uow: UserLinkUnitOfWork,
        now: Callable[[], datetime],
        new_uuid: Callable[[], UUID],
    ) -> None:
        self._status, self._uow = status, uow
        self._now, self._new_uuid = now, new_uuid

    def _fresh(self, expiry: datetime) -> None:
        if expiry <= self._now():
            raise PlatformSubjectLinkUnavailable("User status expired during DB projection")

    async def execute(self, *, issuer: str, subject: str) -> CurrentRauthyUserLink | None:
        if not issuer.startswith("https://") or not 1 <= len(subject) <= 256:
            raise PlatformSubjectLinkUnavailable("invalid issuer or Rauthy subject")
        try:
            status = await self._status.current_status(issuer=issuer, subject=subject)
        except Exception:
            raise PlatformSubjectLinkUnavailable("upstream User status unavailable") from None
        now = self._now()
        status = verify_status(status, issuer, subject, now)
        if not status.active:
            return None
        async with self._uow.transaction() as tx:
            await tx.lock_subject(issuer, subject)
            link = await tx.get(issuer, subject)
            if link is None:
                link = PlatformUserLink(
                    self._new_uuid(), issuer, subject, status.role, True, 1, now, now
                )
                action: ProvisioningAction | None = "panel.user.provisioned"
            else:
                if not link.active:
                    return None
                action = link.sync_role(status.role, now)
            if action is not None:
                await tx.save(link, self._new_uuid(), action)
            self._fresh(status.expires_at)
            result = link.current(status)
        self._fresh(status.expires_at)
        return result
