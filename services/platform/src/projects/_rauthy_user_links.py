"""On-demand membership for real Rauthy subjects after authenticated ingress.

Owner override: first access provisions the provider-owned account, with
rauthy_admin mapped from private Users:read to the Platform operator role.
No directory scans, background synchronization, password or token storage.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from common.platform_db import ControlBase, PlatformDatabase
from projects._oidc_membership_projection import (
    CurrentRauthyUserLink,
)
from projects.application.user_links import (
    TrustedRauthyUserStatusPort as TrustedRauthyUserStatusPort,
)
from projects.domain.user_links import VerifiedRauthyUserStatus as VerifiedRauthyUserStatus


class RauthyUserLinkRow(ControlBase):
    """Current Platform mapping; no password, tokens, refresh or IdP groups."""

    __tablename__ = "rauthy_user_links"
    __table_args__ = (
        UniqueConstraint("issuer", "subject", name="uq_rauthy_user_subject"),
        CheckConstraint("briareus_role IN ('user','operator')", name="ck_rauthy_user_link_role"),
        CheckConstraint("version >= 1", name="ck_rauthy_user_link_version"),
        {"schema": "control"},
    )

    user_id: Mapped[UUID] = mapped_column(primary_key=True)
    issuer: Mapped[str] = mapped_column(String(512))
    subject: Mapped[str] = mapped_column(String(256))
    briareus_role: Mapped[str] = mapped_column(String(16))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PlatformCurrentSubjectLinkReader:
    """Compose exact-subject provisioning with provider and SQL owner adapters."""

    def __init__(
        self,
        *,
        database: PlatformDatabase,
        rauthy_status: TrustedRauthyUserStatusPort,
    ) -> None:
        if database.engine.url.database != "briareus_platform" or rauthy_status is None:
            raise ValueError("Platform link reader requires own DB and real upstream status")
        from projects.application.user_links import ProvisionCurrentSubject
        from projects.infrastructure.user_links import SqlUserLinkUnitOfWork

        self._use_case = ProvisionCurrentSubject(
            rauthy_status,
            SqlUserLinkUnitOfWork(database),
            lambda: datetime.now(UTC),
            uuid4,
        )

    async def current_link(self, *, issuer: str, subject: str) -> CurrentRauthyUserLink | None:
        return await self._use_case.execute(issuer=issuer, subject=subject)


@dataclass(frozen=True, slots=True)
class VerifiedOperatorEnrollment:
    """Already authenticated, scoped operator decision, NEVER browser JSON."""

    operation_uuid: UUID
    approver_uuid: UUID
    user_uuid: UUID
    issuer: str
    subject: str
    role: Literal["user", "operator"]
    can_manage_users: bool
    can_assign_operator: bool
    expires_at: datetime


class TrustedOperatorEnrollmentPort(Protocol):
    async def verify(self, evidence: object) -> VerifiedOperatorEnrollment:
        """Verify signed operator/admin authority from real current owner."""
        ...


class OperatorEnrollmentDenied(Exception):
    """Untrusted or insufficient operator authority for this User binding."""


class OperatorEnrollmentConflict(Exception):
    """A User ID or Rauthy subject is already bound incompatibly."""


class PlatformRauthyEnrollmentService:
    """Compatibility boundary; provider-owned ingress replaces manual links."""

    def __init__(
        self,
        *,
        database: PlatformDatabase,
        decisions: TrustedOperatorEnrollmentPort | None,
        rauthy_status: TrustedRauthyUserStatusPort | None,
    ) -> None:
        if (
            database.engine.url.database != "briareus_platform"
            or decisions is None
            or rauthy_status is None
        ):
            raise ValueError("operator enrollment needs owner DB, proof and upstream")

    async def enroll(self, *, signed_evidence: object) -> CurrentRauthyUserLink:
        del signed_evidence
        raise OperatorEnrollmentDenied(
            "Manual User links are retired; provider-verified ingress owns membership"
        )


@dataclass(frozen=True, slots=True)
class VerifiedOperatorSuspension:
    """Separate signed operator action; never a bearer-only target UUID."""

    operation_uuid: UUID
    approver_uuid: UUID
    target_user_uuid: UUID
    expected_link_version: int
    can_manage_users: bool
    expires_at: datetime


class TrustedOperatorSuspensionPort(Protocol):
    async def verify(self, evidence: object) -> VerifiedOperatorSuspension:
        """Verify independently scoped, current signed user-disable authority."""
        ...


class PlatformRauthySuspensionService:
    """Compatibility boundary; no dormant independent account lifecycle owner."""

    def __init__(
        self,
        *,
        database: PlatformDatabase,
        decisions: TrustedOperatorSuspensionPort,
    ) -> None:
        if database.engine.url.database != "briareus_platform" or decisions is None:
            raise ValueError("suspension requires own DB and trusted operator port")

    async def suspend(self, *, signed_evidence: object) -> int:
        del signed_evidence
        raise OperatorEnrollmentDenied(
            "Manual User suspension is retired; Rauthy owns account status"
        )
