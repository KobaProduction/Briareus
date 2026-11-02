"""Bounded directory facts; visibility never grants membership."""

from dataclasses import dataclass
from uuid import UUID

from projects.domain.ownership import ProjectOwner


@dataclass(frozen=True, slots=True)
class UserProfile:
    name: str | None
    email: str | None
    enabled: bool


@dataclass(frozen=True, slots=True)
class InventoryUserReference:
    uuid: UUID
    subject: str
    role: str
    enabled: bool


@dataclass(frozen=True, slots=True)
class InventoryUser:
    id: UUID
    role: str
    enabled: bool
    name: str | None
    email: str | None


@dataclass(frozen=True, slots=True)
class InventoryTeam:
    id: UUID
    name: str
    owner_user_id: UUID
    member_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class InventoryProject:
    id: UUID
    name: str
    owner_user_id: UUID | None
    owner_team_id: UUID | None

    def __post_init__(self) -> None:
        ProjectOwner.from_ids(self.owner_user_id, self.owner_team_id)


@dataclass(frozen=True, slots=True)
class InventorySnapshot:
    users: tuple[InventoryUserReference, ...]
    teams: tuple[InventoryTeam, ...]
    projects: tuple[InventoryProject, ...]
    truncated: bool


@dataclass(frozen=True, slots=True)
class Inventory:
    users: tuple[InventoryUser, ...]
    teams: tuple[InventoryTeam, ...]
    projects: tuple[InventoryProject, ...]
    truncated: bool
