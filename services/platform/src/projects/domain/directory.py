"""Directory visibility does not confer membership or execution authority."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from projects.domain.ownership import ProjectOwner

DirectoryKind = Literal["teams", "projects"]
DirectoryPermission = Literal["use_resources", "approve_agent_session"]


@dataclass(frozen=True, slots=True)
class DirectoryActor:
    user_id: UUID
    role: Literal["user", "operator"]
    expires_at: datetime

    def can_approve(self, owner_user_id: UUID | None, team_owner_id: UUID | None) -> bool:
        return self.role == "operator" or self.user_id in (owner_user_id, team_owner_id)


@dataclass(frozen=True, slots=True)
class DirectoryTeam:
    id: UUID
    name: str
    owner: bool
    member: bool


@dataclass(frozen=True, slots=True)
class DirectoryProject:
    id: UUID
    name: str
    owner: ProjectOwner
    permissions: tuple[DirectoryPermission, ...]


DirectoryItem = DirectoryTeam | DirectoryProject


@dataclass(frozen=True, slots=True)
class DirectoryPage:
    kind: DirectoryKind
    items: tuple[DirectoryItem, ...]
    has_more: bool
    next_cursor: UUID | None
