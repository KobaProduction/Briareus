"""Platform management invariants, independent of transport and storage."""

from dataclasses import dataclass
from uuid import UUID

from projects.domain.errors import ManagementError as ManagementError
from projects.domain.ownership import ProjectOwner


def identifier(value: object) -> UUID:
    try:
        result = UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise ManagementError(422, "INVALID_IDENTIFIER") from None
    if result.version != 4 or str(result) != value:
        raise ManagementError(422, "INVALID_IDENTIFIER")
    return result


def name(value: object) -> str:
    if not isinstance(value, str):
        raise ManagementError(422, "NAME_REQUIRED")
    result = value.strip()
    if not 1 <= len(result) <= 255 or any(ord(c) < 32 or ord(c) == 127 for c in result):
        raise ManagementError(422, "NAME_INVALID")
    return result


@dataclass(frozen=True, slots=True)
class ManagementOutcome:
    id: UUID
    name: str


@dataclass(slots=True)
class ManagedTeam:
    uuid: UUID
    name: str
    owner_user_uuid: UUID
    resource_revision: int

    def rename(self, expected_name: str, new_name: str) -> None:
        if self.name != expected_name:
            raise ManagementError(409, "NAME_CHANGED")
        self.name = name(new_name)

    def change_member(self, user_uuid: UUID, active: bool) -> None:
        if not active and user_uuid == self.owner_user_uuid:
            raise ManagementError(409, "TEAM_OWNER_REQUIRED")
        self.resource_revision += 1

    def outcome(self) -> ManagementOutcome:
        return ManagementOutcome(self.uuid, self.name)


@dataclass(slots=True)
class ManagedProject:
    uuid: UUID
    name: str
    owner_user_uuid: UUID | None
    owner_team_uuid: UUID | None

    def __post_init__(self) -> None:
        ProjectOwner.from_ids(self.owner_user_uuid, self.owner_team_uuid)

    def rename(self, expected_name: str, new_name: str) -> None:
        if self.name != expected_name:
            raise ManagementError(409, "NAME_CHANGED")
        self.name = name(new_name)

    def outcome(self) -> ManagementOutcome:
        return ManagementOutcome(self.uuid, self.name)
