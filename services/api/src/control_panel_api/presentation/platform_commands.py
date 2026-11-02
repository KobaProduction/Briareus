"""Deployed Platform command boundaries backed by the canonical owner wire models."""

from typing import Literal, Self
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    TypeAdapter,
    ValidationInfo,
    field_validator,
    model_validator,
)

from control_panel_api.domain.management_operations import (
    ChangeTeamMember,
    CreateProject,
    CreateTeam,
    IssueInvitation,
    ManagementOperation,
    ReadDirectory,
    ReadInventory,
    ReadInvitationCapabilities,
    ReadTeam,
    RenameEntity,
    SetInviter,
)
from control_panel_api.domain.platform_management import (
    ManagementCommand,
    ManagementIntent,
    RpcFailure,
)
from runtime_peer.platform_management_wire import (
    DirectoryInput,
    EmptyInput,
    IdentifierInput,
    InvitationInput,
    InviterInput,
    MemberInput,
    NamedInput,
    ProjectInput,
    RenameInput,
)
from service_runtime._uuid_field_validation import _operation_uuid_v4

from .directory_queries import canonical_identifier, page_selection

type MutationInput = (
    RenameInput
    | ProjectInput
    | MemberInput
    | InviterInput
    | InvitationInput
    | NamedInput
    | EmptyInput
)

_INPUT_SCHEMAS: dict[str, TypeAdapter[MutationInput]] = {
    "team.create": TypeAdapter(NamedInput),
    "team.rename": TypeAdapter(RenameInput),
    "team.member.add": TypeAdapter(MemberInput),
    "team.member.remove": TypeAdapter(MemberInput),
    "project.create": TypeAdapter(ProjectInput),
    "project.rename": TypeAdapter(RenameInput),
    "invitation.capabilities": TypeAdapter(EmptyInput),
    "invitation.issue": TypeAdapter(InvitationInput),
    "inviter.set": TypeAdapter(InviterInput),
}


def _operation(action: str, data: MutationInput) -> ManagementOperation:
    match data:
        case RenameInput():
            kind: Literal["team", "project"] = "team" if action == "team.rename" else "project"
            return RenameEntity(kind, canonical_identifier(data.id), data.name, data.expected_name)
        case ProjectInput():
            team_id = canonical_identifier(data.team_id) if data.team_id is not None else None
            return CreateProject(data.name, team_id)
        case MemberInput():
            return ChangeTeamMember(
                canonical_identifier(data.id),
                canonical_identifier(data.user_id),
                action == "team.member.add",
            )
        case InviterInput():
            return SetInviter(canonical_identifier(data.user_id), data.enabled)
        case InvitationInput():
            return IssueInvitation(data.email)
        case NamedInput():
            return CreateTeam(data.name)
        case EmptyInput():
            return ReadInvitationCapabilities()


class PlatformCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    operation_uuid: UUID
    action: Literal[
        "team.create",
        "team.rename",
        "team.member.add",
        "team.member.remove",
        "project.create",
        "project.rename",
        "invitation.capabilities",
        "invitation.issue",
        "inviter.set",
    ]
    data: MutationInput

    operation_v4 = field_validator("operation_uuid")(staticmethod(_operation_uuid_v4))

    @field_validator("data", mode="before")
    @classmethod
    def operation_input(cls, value: object, info: ValidationInfo[None]) -> MutationInput:
        action = info.data.get("action")
        if not isinstance(action, str) or action not in _INPUT_SCHEMAS:
            raise ValueError("Unknown management operation")
        return _INPUT_SCHEMAS[action].validate_python(value)

    @model_validator(mode="after")
    def operation_identifiers(self) -> Self:
        _operation(self.action, self.data)
        return self

    def command(self) -> ManagementCommand:
        return ManagementCommand(self.operation_uuid, _operation(self.action, self.data))


def management_rpc_intent(method: str, params: object) -> ManagementIntent:
    if method == "platform.command":
        try:
            command = PlatformCommand.model_validate(params).command()
        except ValueError:
            raise RpcFailure("COMMAND_INVALID") from None
        return ManagementIntent(command, mutation=True)
    if method == "platform.directory":
        try:
            selected = DirectoryInput.model_validate(params)
        except ValueError:
            raise RpcFailure("COMMAND_INVALID") from None
        operation = ReadDirectory(selected.kind, page_selection(selected))
        return ManagementIntent(ManagementCommand(uuid4(), operation), mutation=False)
    if method == "platform.team":
        try:
            selected_team = IdentifierInput.model_validate(params)
            team_uuid = canonical_identifier(selected_team.id)
        except ValueError:
            raise RpcFailure("TEAM_MEMBERSHIP_REQUIRED") from None
        return ManagementIntent(ManagementCommand(uuid4(), ReadTeam(team_uuid)), mutation=False)
    if params:
        raise RpcFailure("COMMAND_INVALID")
    return ManagementIntent(ManagementCommand(uuid4(), ReadInventory()), mutation=False)
