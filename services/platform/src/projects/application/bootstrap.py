"""One-time trust root creation with current independent and provider evidence."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Protocol

from projects.application.user_links import TrustedRauthyUserStatusPort
from projects.domain.bootstrap import (
    FirstOperatorBootstrapDenied,
    FirstOperatorBootstrapUnavailable,
    VerifiedFirstOperatorApproval,
    require_active_status,
    verified_approval,
)
from projects.domain.membership import CurrentRauthyUserLink


class TrustedFirstOperatorAuthority(Protocol):
    async def verify(self, evidence: object) -> VerifiedFirstOperatorApproval: ...


class BootstrapTransaction(Protocol):
    async def lock(self) -> None: ...
    async def require_empty(self) -> None: ...
    async def create(self, approval: VerifiedFirstOperatorApproval, now: datetime) -> None: ...


class BootstrapUnitOfWork(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[BootstrapTransaction]: ...


class BootstrapFirstOperator:
    def __init__(
        self,
        authority: TrustedFirstOperatorAuthority,
        status: TrustedRauthyUserStatusPort,
        uow: BootstrapUnitOfWork,
        allowed_issuers: frozenset[str],
        now: Callable[[], datetime],
    ) -> None:
        self._authority, self._status, self._uow = authority, status, uow
        self._issuers, self._now = allowed_issuers, now

    def _fresh(self, deadline: datetime) -> None:
        if deadline <= self._now():
            raise FirstOperatorBootstrapDenied("bootstrap signed proof expired")

    async def execute(self, signed_evidence: object) -> CurrentRauthyUserLink:
        try:
            approval = await self._authority.verify(signed_evidence)
        except Exception:
            raise FirstOperatorBootstrapDenied("signed first-operator approval required") from None
        approval = verified_approval(approval, self._issuers, self._now())
        try:
            status = await self._status.current_status(
                issuer=approval.rauthy_issuer, subject=approval.rauthy_subject
            )
        except Exception:
            raise FirstOperatorBootstrapUnavailable("provider user status unavailable") from None
        status = require_active_status(status, approval, self._now())
        deadline = min(approval.expires_at, status.expires_at)
        try:
            async with self._uow.transaction() as tx:
                await tx.lock()
                await tx.require_empty()
                self._fresh(deadline)
                await tx.create(approval, self._now())
                self._fresh(deadline)
            if deadline <= self._now():
                raise FirstOperatorBootstrapUnavailable(
                    "first operator outcome indeterminate after proof expiry"
                )
        except (FirstOperatorBootstrapDenied, FirstOperatorBootstrapUnavailable):
            raise
        except Exception:
            raise FirstOperatorBootstrapUnavailable("own Platform database unavailable") from None
        return CurrentRauthyUserLink(
            approval.rauthy_issuer,
            approval.rauthy_subject,
            approval.user_uuid,
            True,
            "operator",
            1,
            deadline,
        )
