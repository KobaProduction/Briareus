"""Owner directory parameters become typed selections before application dispatch."""

from uuid import UUID

from control_panel_api.domain.agent_directory import AgentQuery
from control_panel_api.domain.directory_queries import UNSPECIFIED, DirectoryPageSelection
from runtime_peer.platform_management_wire import AgentGetInput, AgentPageInput, DirectoryInput


def canonical_identifier(value: str) -> UUID:
    identifier = UUID(value)
    if identifier.version != 4 or str(identifier) != value:
        raise ValueError("Canonical UUIDv4 required")
    return identifier


def page_selection(value: DirectoryInput | AgentPageInput) -> DirectoryPageSelection:
    return DirectoryPageSelection(
        value.cursor if "cursor" in value.model_fields_set else UNSPECIFIED,
        value.limit if "limit" in value.model_fields_set else UNSPECIFIED,
    )


def agent_query(method: str, params: object) -> AgentQuery:
    if method == "agents.get":
        selected = AgentGetInput.model_validate(params)
        return AgentQuery(
            canonical_identifier(selected.project_uuid), canonical_identifier(selected.id)
        )
    if method != "agents.list":
        raise ValueError("Unknown agent directory operation")
    page = AgentPageInput.model_validate(params)
    return AgentQuery(canonical_identifier(page.project_uuid), page=page_selection(page))
