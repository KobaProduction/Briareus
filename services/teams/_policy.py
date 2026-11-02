"""Compatibility import preserving the current ownership error contract."""

from common.platform_errors import AccessDenied
from common.platform_ids import UserId

from .domain import Team, TeamAccessDenied
from .domain import require_team_owner as _require_team_owner


def require_team_owner(team: Team, actor: UserId) -> None:
    try:
        _require_team_owner(team, actor)
    except TeamAccessDenied as error:
        raise AccessDenied(str(error)) from error


__all__ = ["require_team_owner"]
