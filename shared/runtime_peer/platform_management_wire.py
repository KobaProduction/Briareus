"""Concrete existing Panel commands; wire presence is preserved for signed digests."""

import hashlib
import json
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    TypeAdapter,
    field_validator,
)

from runtime_peer.event_window_wire import EventWindowRequest
from service_runtime._uuid_field_validation import _operation_uuid_v4


class CommandInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EmptyInput(CommandInput):
    pass


class NamedInput(CommandInput):
    name: StrictStr


class RenameInput(NamedInput):
    id: StrictStr
    expected_name: StrictStr


class MemberInput(CommandInput):
    id: StrictStr
    user_id: StrictStr


class ProjectInput(NamedInput):
    team_id: StrictStr | None


class IdentifierInput(CommandInput):
    id: StrictStr


class DirectoryInput(CommandInput):
    kind: Literal["teams", "projects"]
    cursor: StrictStr | None = None
    limit: StrictInt = 50


class AgentPageInput(CommandInput):
    project_uuid: StrictStr
    cursor: StrictStr | None = None
    limit: StrictInt = 50


class AgentGetInput(IdentifierInput):
    project_uuid: StrictStr


class InviterInput(CommandInput):
    user_id: StrictStr
    enabled: StrictBool


class InvitationInput(CommandInput):
    email: StrictStr


class PanelCommand[InputT: BaseModel](BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    issuer: str = Field(min_length=12, max_length=512)
    subject: str = Field(min_length=1, max_length=256)
    operation_uuid: UUID
    action: str
    data: InputT

    operation_v4 = field_validator("operation_uuid")(staticmethod(_operation_uuid_v4))

    def wire_bytes(self) -> bytes:
        # Original data was a dictionary: absent optional keys stayed absent.
        # Keep that exact signed shape rather than adding model defaults.
        wire = self.model_dump(
            mode="json",
            include={
                "issuer": True,
                "subject": True,
                "operation_uuid": True,
                "action": True,
                "data": self.data.model_fields_set,
            },
        )
        return json.dumps(wire, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()

    def fingerprint(self) -> str:
        return hashlib.sha256(self.wire_bytes()).hexdigest()


class CreateTeamQuery(PanelCommand[NamedInput]):
    action: Literal["team.create"]


class RenameTeamQuery(PanelCommand[RenameInput]):
    action: Literal["team.rename"]


class ChangeMemberQuery(PanelCommand[MemberInput]):
    action: Literal["team.member.add", "team.member.remove"]


class CreateProjectQuery(PanelCommand[ProjectInput]):
    action: Literal["project.create"]


class RenameProjectQuery(PanelCommand[RenameInput]):
    action: Literal["project.rename"]


class DirectoryQuery(PanelCommand[DirectoryInput]):
    action: Literal["directory"]


class TeamReadQuery(PanelCommand[IdentifierInput]):
    action: Literal["team.read"]


class AgentListQuery(PanelCommand[AgentPageInput]):
    action: Literal["agents.list"]


class AgentGetQuery(PanelCommand[AgentGetInput]):
    action: Literal["agents.get"]


class InventoryQuery(PanelCommand[EmptyInput]):
    action: Literal["inventory"]
    data: EmptyInput = Field(default_factory=EmptyInput)


class EventsQuery(PanelCommand[EventWindowRequest]):
    action: Literal["events.read"]


class InvitationCapabilitiesQuery(PanelCommand[EmptyInput]):
    action: Literal["invitation.capabilities"]
    data: EmptyInput = Field(default_factory=EmptyInput)


class IssueInvitationQuery(PanelCommand[InvitationInput]):
    action: Literal["invitation.issue"]


class SetInviterQuery(PanelCommand[InviterInput]):
    action: Literal["inviter.set"]


type MutationQuery = (
    CreateTeamQuery | RenameTeamQuery | ChangeMemberQuery | CreateProjectQuery | RenameProjectQuery
)

type InvitationQuery = InvitationCapabilitiesQuery | IssueInvitationQuery | SetInviterQuery

type ManagementQuery = (
    MutationQuery
    | InvitationQuery
    | DirectoryQuery
    | TeamReadQuery
    | AgentListQuery
    | AgentGetQuery
    | InventoryQuery
    | EventsQuery
)

MANAGEMENT_QUERY = TypeAdapter[ManagementQuery](
    Annotated[ManagementQuery, Field(discriminator="action")]
)

type ManagementInput = (
    RenameInput
    | ProjectInput
    | MemberInput
    | DirectoryInput
    | AgentPageInput
    | AgentGetInput
    | IdentifierInput
    | InviterInput
    | InvitationInput
    | EventWindowRequest
    | NamedInput
    | EmptyInput
)


class ManagementEnvelope(PanelCommand[ManagementInput]):
    """Concrete owner commands bound to the BFF's verified human identity."""
