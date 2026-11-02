"""Encode typed management intents using the owner's canonical signed wire shape."""

from control_panel_api.domain.agent_directory import AgentQuery
from control_panel_api.domain.directory_queries import DirectoryPageSelection, Unspecified
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
from runtime_peer.platform_management_wire import (
    AgentGetInput,
    AgentPageInput,
    DirectoryInput,
    EmptyInput,
    IdentifierInput,
    InvitationInput,
    InviterInput,
    ManagementInput,
    MemberInput,
    NamedInput,
    ProjectInput,
    RenameInput,
)


def _page_presence(
    model: DirectoryInput | AgentPageInput, selection: DirectoryPageSelection
) -> None:
    # Presence belongs to the signed transport. Default values must not invent
    # keys that the browser omitted, even when they have equivalent meaning.
    if isinstance(selection.cursor, Unspecified):
        model.model_fields_set.discard("cursor")
    if isinstance(selection.limit, Unspecified):
        model.model_fields_set.discard("limit")


def directory_input(selection: ReadDirectory) -> DirectoryInput:
    page = selection.page
    result = DirectoryInput(
        kind=selection.kind,
        cursor=None if isinstance(page.cursor, Unspecified) else page.cursor,
        limit=50 if isinstance(page.limit, Unspecified) else page.limit,
    )
    _page_presence(result, page)
    return result


def agent_input(query: AgentQuery) -> AgentGetInput | AgentPageInput:
    if query.id is not None:
        return AgentGetInput(id=str(query.id), project_uuid=str(query.project))
    page = query.page
    result = AgentPageInput(
        project_uuid=str(query.project),
        cursor=None if isinstance(page.cursor, Unspecified) else page.cursor,
        limit=50 if isinstance(page.limit, Unspecified) else page.limit,
    )
    _page_presence(result, page)
    return result


def operation_input(operation: ManagementOperation) -> ManagementInput:
    match operation:
        case CreateTeam(name):
            return NamedInput(name=name)
        case CreateProject(name, team_id):
            return ProjectInput(name=name, team_id=str(team_id) if team_id is not None else None)
        case RenameEntity(_, identifier, name, expected_name):
            return RenameInput(id=str(identifier), name=name, expected_name=expected_name)
        case ChangeTeamMember(identifier, user_id, _):
            return MemberInput(id=str(identifier), user_id=str(user_id))
        case ReadDirectory():
            return directory_input(operation)
        case ReadTeam(identifier):
            return IdentifierInput(id=str(identifier))
        case ReadInventory() | ReadInvitationCapabilities():
            return EmptyInput()
        case IssueInvitation(email):
            return InvitationInput(email=email)
        case SetInviter(user_id, enabled):
            return InviterInput(user_id=str(user_id), enabled=enabled)
