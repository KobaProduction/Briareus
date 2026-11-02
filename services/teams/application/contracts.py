"""SDK-free commands and audit facts for the Teams use cases."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

TeamAuditAction = Literal[
    "team.created",
    "operator.teams_read",
    "operator.team_members_read",
    "team.member_added",
    "team.member_removed",
    "team.owner_transferred",
]


@dataclass(frozen=True, slots=True)
class TeamActor:
    user_uuid: UUID
    is_operator: bool


@dataclass(frozen=True, slots=True)
class CreateTeam:
    name: str


@dataclass(frozen=True, slots=True)
class MutateMember:
    team_uuid: UUID
    user_uuid: UUID
    expected_version: int


@dataclass(frozen=True, slots=True)
class TransferOwner:
    team_uuid: UUID
    new_owner_uuid: UUID
    expected_version: int


@dataclass(frozen=True, slots=True)
class TeamAudit:
    actor_uuid: UUID
    action: TeamAuditAction
    target: UUID | str
    team_uuid: UUID | None = None
    new_owner_uuid: UUID | None = None
