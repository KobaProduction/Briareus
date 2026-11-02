"""Panel input adaptation and composition for the paged Platform directory."""

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from common.platform_db import PlatformDatabase
from projects._oidc_membership_projection import CurrentRauthyPlatformMembership
from projects.application.directory import DirectoryError, DirectoryQuery, ReadDirectory
from projects.domain.directory import DirectoryActor, DirectoryPage
from projects.domain.management import ManagementError
from projects.infrastructure.directory import (
    CurrentLinkProjection,
    ProjectionDirectoryAuthority,
    SqlDirectoryReader,
)
from projects.presentation.management_inputs import DirectoryQuery as DirectoryCommand


class DirectoryService(Protocol):
    @property
    def db(self) -> PlatformDatabase: ...

    @property
    def projection(self) -> CurrentLinkProjection: ...


def directory_query(query: DirectoryCommand) -> DirectoryQuery:
    return DirectoryQuery(
        query.issuer,
        query.subject,
        query.data.kind,
        query.data.limit,
        directory_cursor(query.data.cursor),
    )


def directory_cursor(value: object) -> UUID | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise DirectoryError(422, "DIRECTORY_CURSOR_INVALID")
    try:
        parsed = UUID(value)
    except ValueError:
        raise DirectoryError(422, "DIRECTORY_CURSOR_INVALID") from None
    if parsed.version != 4 or str(parsed) != value:
        raise DirectoryError(422, "DIRECTORY_CURSOR_INVALID")
    return parsed


async def read_directory(
    service: DirectoryService,
    query: DirectoryCommand,
    actor: CurrentRauthyPlatformMembership,
    deadline: datetime,
) -> DirectoryPage:
    use_case = ReadDirectory(
        SqlDirectoryReader(service.db),
        ProjectionDirectoryAuthority(service.projection),
        lambda: datetime.now(UTC),
    )
    try:
        return await use_case.execute(
            directory_query(query),
            DirectoryActor(actor.user_id, actor.role, actor.expires_at),
            deadline,
        )
    except DirectoryError as exc:
        raise ManagementError(exc.status, exc.code) from exc
