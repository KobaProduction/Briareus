"""A project has exactly one personal or team owner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from projects.domain.errors import ManagementError


@dataclass(frozen=True, slots=True)
class ProjectOwner:
    kind: Literal["user", "team"]
    id: UUID

    @classmethod
    def from_ids(cls, user_uuid: UUID | None, team_uuid: UUID | None) -> ProjectOwner:
        if user_uuid is not None and team_uuid is None:
            return cls("user", user_uuid)
        if team_uuid is not None and user_uuid is None:
            return cls("team", team_uuid)
        raise ManagementError(409, "PROJECT_OWNER_INVALID")
