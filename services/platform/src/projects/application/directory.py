"""Read a bounded directory, then revalidate the exact current authority."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from projects.application._authority_bindings import _ReadAuthorityBinding
from projects.domain.directory import DirectoryActor, DirectoryItem, DirectoryKind, DirectoryPage
from projects.domain.errors import _StatusCodeError


class DirectoryError(_StatusCodeError):
    pass


@dataclass(frozen=True, slots=True)
class DirectoryQuery:
    issuer: str
    subject: str
    kind: DirectoryKind
    limit: int
    cursor: UUID | None

    def __post_init__(self) -> None:
        if self.kind not in ("teams", "projects") or type(self.limit) is not int:
            raise DirectoryError(422, "DIRECTORY_QUERY_INVALID")
        if not 1 <= self.limit <= 100:
            raise DirectoryError(422, "DIRECTORY_QUERY_INVALID")
        if self.cursor is not None and self.cursor.version != 4:
            raise DirectoryError(422, "DIRECTORY_CURSOR_INVALID")


class DirectoryReader(Protocol):
    async def read(
        self, query: DirectoryQuery, actor: DirectoryActor
    ) -> tuple[DirectoryItem, ...]: ...


class DirectoryAuthority(Protocol):
    async def current(self, issuer: str, subject: str) -> DirectoryActor | None: ...


class ReadDirectory(_ReadAuthorityBinding[DirectoryReader, DirectoryAuthority]):
    async def execute(
        self, query: DirectoryQuery, actor: DirectoryActor, deadline: datetime
    ) -> DirectoryPage:
        rows = await self._reader.read(query, actor)
        fresh = await self._authority.current(query.issuer, query.subject)
        if fresh is None or fresh.user_id != actor.user_id or fresh.role != actor.role:
            raise DirectoryError(403, "DIRECTORY_AUTHORITY_CHANGED")
        if min(deadline, fresh.expires_at) <= self._now():
            raise DirectoryError(403, "DIRECTORY_AUTHORITY_CHANGED")
        items = rows[: query.limit]
        more = len(rows) > query.limit
        return DirectoryPage(query.kind, items, more, items[-1].id if more else None)
