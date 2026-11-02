"""Human management operations; owner policies remain authoritative for mutations."""

from dataclasses import dataclass
from typing import ClassVar, Literal
from uuid import UUID

from .directory_queries import DirectoryPageSelection


@dataclass(frozen=True, slots=True)
class NamedCreation:
    name: str


@dataclass(frozen=True, slots=True)
class CreateTeam(NamedCreation):
    action: ClassVar[str] = "team.create"


@dataclass(frozen=True, slots=True)
class CreateProject(NamedCreation):
    team_id: UUID | None
    action: ClassVar[str] = "project.create"


@dataclass(frozen=True, slots=True)
class RenameEntity:
    kind: Literal["team", "project"]
    id: UUID
    name: str
    expected_name: str

    @property
    def action(self) -> str:
        return self.kind + ".rename"


@dataclass(frozen=True, slots=True)
class ChangeTeamMember:
    id: UUID
    user_id: UUID
    add: bool

    @property
    def action(self) -> str:
        return "team.member.add" if self.add else "team.member.remove"


@dataclass(frozen=True, slots=True)
class ReadDirectory:
    kind: Literal["teams", "projects"]
    page: DirectoryPageSelection
    action: ClassVar[str] = "directory"


@dataclass(frozen=True, slots=True)
class ReadTeam:
    id: UUID
    action: ClassVar[str] = "team.read"


@dataclass(frozen=True, slots=True)
class ReadInventory:
    action: ClassVar[str] = "inventory"


@dataclass(frozen=True, slots=True)
class ReadInvitationCapabilities:
    action: ClassVar[str] = "invitation.capabilities"


@dataclass(frozen=True, slots=True)
class IssueInvitation:
    email: str
    action: ClassVar[str] = "invitation.issue"


@dataclass(frozen=True, slots=True)
class SetInviter:
    user_id: UUID
    enabled: bool
    action: ClassVar[str] = "inviter.set"


type ManagementOperation = (
    CreateTeam
    | CreateProject
    | RenameEntity
    | ChangeTeamMember
    | ReadDirectory
    | ReadTeam
    | ReadInventory
    | ReadInvitationCapabilities
    | IssueInvitation
    | SetInviter
)
