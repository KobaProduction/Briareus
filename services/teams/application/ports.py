"""Teams application boundaries; the caller owns the surrounding transaction."""

from typing import Protocol
from uuid import UUID

from teams.domain import Team, TeamMembership

from .contracts import TeamAudit


class TargetUserPort(Protocol):
    async def enabled(self, user_uuid: UUID) -> bool: ...


class TeamAuditPort(Protocol):
    def record(self, audit: TeamAudit) -> None: ...


class TeamStore(Protocol):
    async def get(self, team_uuid: UUID, *, lock: bool = False) -> Team | None: ...

    async def create(self, name: str, owner_uuid: UUID) -> Team: ...

    async def list_all(self) -> list[Team]: ...

    async def list_for_user(self, user_uuid: UUID) -> list[Team]: ...

    async def list_members(self, team_uuid: UUID) -> list[TeamMembership]: ...

    async def active_member(self, team_uuid: UUID, user_uuid: UUID) -> bool: ...

    async def change_membership(
        self, team_uuid: UUID, user_uuid: UUID, *, active: bool
    ) -> bool: ...

    def save(self, team: Team) -> None: ...
