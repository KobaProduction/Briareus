"""Composition and compatible imports for current Platform membership."""

from datetime import UTC, datetime
from uuid import UUID

from common.platform_db import PlatformDatabase
from projects.application.membership import ResolveMembership
from projects.application.membership import TrustedRauthyUserLinkPort as TrustedRauthyUserLinkPort
from projects.domain.membership import (
    CurrentRauthyPlatformMembership,
    CurrentRauthyUserLink,
)
from projects.domain.membership import PlatformProjectMembership as PlatformProjectMembership
from projects.domain.membership import (
    PlatformSubjectLinkUnavailable as PlatformSubjectLinkUnavailable,
)
from projects.domain.membership import PlatformTeamMembership as PlatformTeamMembership
from projects.infrastructure.membership import SqlMembershipReader

__all__ = [
    "CurrentRauthyPlatformMembership",
    "CurrentRauthyUserLink",
    "PlatformOidcMembershipProjection",
    "PlatformProjectMembership",
    "PlatformSubjectLinkUnavailable",
    "PlatformTeamMembership",
    "TrustedRauthyUserLinkPort",
]


class PlatformOidcMembershipProjection:
    def __init__(
        self,
        *,
        database: PlatformDatabase,
        subject_links: TrustedRauthyUserLinkPort,
    ) -> None:
        if database.engine.url.database != "briareus_platform" or subject_links is None:
            raise ValueError("Platform OIDC projection needs its own DB and signed User link")
        self._use_case = ResolveMembership(
            subject_links,
            SqlMembershipReader(database),
            lambda: datetime.now(UTC),
        )

    async def _current_link(self, *, issuer: str, subject: str) -> CurrentRauthyUserLink | None:
        return await self._use_case.current_link(issuer=issuer, subject=subject)

    async def resolve(self, *, issuer: str, subject: str) -> CurrentRauthyPlatformMembership | None:
        return await self._use_case.directory(issuer=issuer, subject=subject)

    async def resolve_project(
        self,
        *,
        issuer: str,
        subject: str,
        project_uuid: UUID,
    ) -> CurrentRauthyPlatformMembership | None:
        return await self._use_case.project(
            issuer=issuer, subject=subject, project_uuid=project_uuid
        )
