"""Resolve current directory or exact-project authority through owner ports."""

from collections.abc import Callable
from datetime import datetime
from typing import Protocol
from uuid import UUID

from projects.domain.membership import (
    CurrentRauthyPlatformMembership,
    CurrentRauthyUserLink,
    MembershipFacts,
    PlatformSubjectLinkUnavailable,
    current_link,
    valid_uuid4,
)


class TrustedRauthyUserLinkPort(Protocol):
    async def current_link(self, *, issuer: str, subject: str) -> CurrentRauthyUserLink | None: ...


class MembershipReader(Protocol):
    async def directory(self, actor: CurrentRauthyUserLink) -> MembershipFacts: ...
    async def project(
        self, actor: CurrentRauthyUserLink, project_uuid: UUID
    ) -> MembershipFacts | None: ...


class ResolveMembership:
    def __init__(
        self,
        links: TrustedRauthyUserLinkPort,
        reader: MembershipReader,
        now: Callable[[], datetime],
    ) -> None:
        self._links = links
        self._reader = reader
        self._now = now

    async def current_link(self, *, issuer: str, subject: str) -> CurrentRauthyUserLink | None:
        if not issuer.startswith("https://") or not 1 <= len(subject) <= 256:
            raise PlatformSubjectLinkUnavailable("invalid trusted issuer or subject")
        try:
            link = await self._links.current_link(issuer=issuer, subject=subject)
        except Exception:
            raise PlatformSubjectLinkUnavailable("signed Rauthy subject link unavailable") from None
        return None if link is None else current_link(link, issuer, subject, self._now())

    def _fresh(self, link: CurrentRauthyUserLink) -> None:
        if link.expires_at <= self._now():
            raise PlatformSubjectLinkUnavailable("Rauthy User binding expired during read")

    async def directory(
        self, *, issuer: str, subject: str
    ) -> CurrentRauthyPlatformMembership | None:
        link = await self.current_link(issuer=issuer, subject=subject)
        if link is None:
            return None
        facts = await self._reader.directory(link)
        self._fresh(link)
        return facts.for_actor(link)

    async def project(
        self,
        *,
        issuer: str,
        subject: str,
        project_uuid: UUID,
    ) -> CurrentRauthyPlatformMembership | None:
        if not valid_uuid4(project_uuid):
            raise PlatformSubjectLinkUnavailable("invalid exact Project selector")
        link = await self.current_link(issuer=issuer, subject=subject)
        if link is None:
            return None
        facts = await self._reader.project(link, project_uuid)
        if facts is None:
            return None
        self._fresh(link)
        return facts.for_actor(link)
