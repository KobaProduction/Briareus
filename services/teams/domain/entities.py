"""Immutable Team and membership facts owned by the Teams context."""

from dataclasses import dataclass

from common.platform_ids import TeamId, UserId


@dataclass(frozen=True, slots=True)
class Team:
    id: TeamId
    name: str
    owner_user_id: UserId
    version: int


@dataclass(frozen=True, slots=True)
class TeamMembership:
    team_id: TeamId
    user_id: UserId
    active: bool
