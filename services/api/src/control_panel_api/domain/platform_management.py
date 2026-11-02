"""Control Panel management commands and owner responses; no owner persistence model."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from .management_operations import ManagementOperation, ReadTeam
from .panel_protocol import PanelContext


class RpcFailure(Exception):
    def __init__(self, code: str, *, uncertain: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.uncertain = uncertain


@dataclass(frozen=True, slots=True)
class ManagementCommand:
    operation_uuid: UUID
    operation: ManagementOperation

    @property
    def action(self) -> str:
        return self.operation.action


@dataclass(frozen=True, slots=True)
class ManagementIntent:
    command: ManagementCommand
    mutation: bool

    @property
    def team_uuid(self) -> UUID | None:
        operation = self.command.operation
        return operation.id if isinstance(operation, ReadTeam) else None

    @property
    def invitation(self) -> bool:
        return self.command.action in {"invitation.capabilities", "invitation.issue"}

    def requires_operator(self) -> bool:
        return self.command.action not in {"directory", "team.read"} and not self.invitation

    def authorize(self, context: PanelContext) -> None:
        proof = context.proof
        if (
            self.command.action == "team.read"
            and not proof.directory_paged
            and not any(team.team_uuid == self.team_uuid for team in proof.teams)
        ):
            raise RpcFailure("TEAM_MEMBERSHIP_REQUIRED")
        if self.requires_operator() and proof.role != "operator":
            raise RpcFailure("PLATFORM_OPERATOR_REQUIRED")

    def authority_continues(self, current: PanelContext, original: PanelContext) -> bool:
        if current.proof.user_uuid != original.proof.user_uuid:
            return False
        if self.requires_operator() and current.proof.role != "operator":
            return False
        if self.command.action != "team.read":
            return True
        if current.proof.role != original.proof.role:
            return False
        return current.proof.directory_paged or any(
            team.team_uuid == self.team_uuid for team in current.proof.teams
        )


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


@dataclass(frozen=True, slots=True)
class ManagementInventory:
    users: tuple[InventoryUser, ...]
    teams: tuple[InventoryTeam, ...]
    projects: tuple[InventoryProject, ...]
    truncated: bool


@dataclass(frozen=True, slots=True)
class DirectoryOwner:
    kind: Literal["user", "team"]
    id: UUID


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
    owner: DirectoryOwner
    permissions: tuple[Literal["use_resources", "approve_agent_session"], ...]


@dataclass(frozen=True, slots=True)
class ManagementDirectory:
    kind: Literal["teams", "projects"]
    items: tuple[DirectoryTeam | DirectoryProject, ...]
    has_more: bool
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class ManagementOutcome:
    id: UUID
    name: str


@dataclass(frozen=True, slots=True)
class InvitationCapabilities:
    can_invite: bool
    can_manage_inviters: bool
    inviter_ids: tuple[UUID, ...]
    unavailable_reason: str | None


@dataclass(frozen=True, slots=True)
class InviterOutcome:
    id: UUID
    enabled: bool
    state: str = "committed"


@dataclass(frozen=True, slots=True)
class InvitationOutcome:
    id: str
    state: str = "provider_created"
    delivery: str = "unconfirmed"


@dataclass(frozen=True, slots=True)
class OwnerError:
    code: str


@dataclass(frozen=True, slots=True)
class ManagementErrorBody:
    error: OwnerError


type ManagementOutput = (
    ManagementInventory
    | ManagementDirectory
    | ManagementOutcome
    | InvitationCapabilities
    | InviterOutcome
    | InvitationOutcome
)


@dataclass(frozen=True, slots=True)
class ManagementReceipt:
    status: int
    result: ManagementOutput | ManagementErrorBody
