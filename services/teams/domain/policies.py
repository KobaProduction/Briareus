"""Team-only invariant checks; no persistence or HTTP dependencies."""

from common.platform_ids import UserId

from .entities import Team
from .errors import TeamAccessDenied, TeamConflict, TeamInvalidInput


def require_team_owner(team: Team, actor: UserId) -> None:
    if team.owner_user_id != actor:
        raise TeamAccessDenied("Team owner required to administer membership or ownership")


def team_name(value: str) -> str:
    name = value.strip()
    if not 1 <= len(name) <= 255:
        raise TeamInvalidInput("name must be 1-255 characters")
    return name


def require_team_version(team: Team, expected_version: int) -> None:
    if team.version != expected_version:
        raise TeamConflict("Team version mismatch")


def require_removable_member(team: Team, user_uuid: UserId) -> None:
    if team.owner_user_id == user_uuid:
        raise TeamConflict("Team owner cannot be removed from membership")
