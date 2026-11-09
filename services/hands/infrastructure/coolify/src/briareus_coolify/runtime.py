from __future__ import annotations

from briareus_control_panel_client.settings import ControlPanelClientSettings
from briareus_hand_runtime import ProviderClientCache
from briareus_hand_runtime.runtime_common import (
    build_private_mcp,
    management_client,
    private_http_app,
)
from briareus_hand_runtime.settings import PrivateRuntimeSettings
from briareus_json_values import JsonObject, JsonValue
from briareus_tool_annotations import READ_EXTERNAL

from briareus_coolify.client import CoolifyClient

_private = PrivateRuntimeSettings()
_management = management_client(ControlPanelClientSettings())
_context = ProviderClientCache(_management, "coolify", CoolifyClient)
mcp = build_private_mcp("coolify", _management)


@mcp.tool(title="Coolify sources", annotations=READ_EXTERNAL)
def coolify_sources() -> JsonObject:
    """List configured coolify sources without exposing credentials."""
    return _context.sources().model_dump(mode="json")


@mcp.tool(title="Coolify connection", annotations=READ_EXTERNAL)
def coolify_connection(account_id: str) -> JsonObject:
    """Show safe metadata for one configured coolify source."""
    return _context.client(account_id).account_summary()


@mcp.tool(title="Infrastructure team", annotations=READ_EXTERNAL)
def coolify_current_team(account_id: str) -> JsonObject:
    """Read the current team from a selected Coolify source."""
    return _context.client(account_id).current_team()


@mcp.tool(title="List infrastructure servers", annotations=READ_EXTERNAL)
def coolify_list_servers(account_id: str) -> JsonValue:
    """List safe server metadata from a selected Coolify source."""
    return _context.client(account_id).servers()


@mcp.tool(title="List server resources", annotations=READ_EXTERNAL)
def coolify_server_resources(account_id: str, server_uuid: str) -> JsonValue:
    """List safe resource identity/status metadata for one Coolify server."""
    return _context.client(account_id).server_resources(server_uuid)


@mcp.tool(title="List infrastructure applications", annotations=READ_EXTERNAL)
def coolify_list_applications(account_id: str) -> JsonValue:
    """List applications from a selected Coolify source."""
    return _context.client(account_id).applications()


@mcp.tool(title="Infrastructure application", annotations=READ_EXTERNAL)
def coolify_get_application(account_id: str, uuid: str) -> JsonObject:
    """Read one application from a selected Coolify source."""
    return _context.client(account_id).application(uuid)


@mcp.tool(title="Infrastructure application storages", annotations=READ_EXTERNAL)
def coolify_application_storages(account_id: str, application_uuid: str) -> JsonObject:
    """List safe Coolify storage topology without file contents or host filesystem paths."""
    return _context.client(account_id).application_storages(application_uuid)


@mcp.tool(title="Infrastructure application variables", annotations=READ_EXTERNAL)
def coolify_application_variables(account_id: str, application_uuid: str) -> JsonObject:
    """List safe Coolify application variable metadata; values are never returned."""
    return _context.client(account_id).application_variables(application_uuid)


@mcp.tool(title="List infrastructure deployments", annotations=READ_EXTERNAL)
def coolify_list_deployments(account_id: str) -> JsonValue:
    """List deployment metadata from a selected Coolify source."""
    return _context.client(account_id).deployments()


@mcp.tool(title="List application deployments", annotations=READ_EXTERNAL)
def coolify_list_application_deployments(
    account_id: str,
    application_uuid: str,
) -> JsonValue:
    """List deployments for one application in a selected Coolify source."""
    return _context.client(account_id).application_deployments(application_uuid)


@mcp.tool(title="Infrastructure deployment", annotations=READ_EXTERNAL)
def coolify_get_deployment(account_id: str, uuid: str) -> JsonObject:
    """Read one deployment from a selected Coolify source."""
    return _context.client(account_id).deployment(uuid)


@mcp.tool(title="Infrastructure deployment logs", annotations=READ_EXTERNAL)
def coolify_get_deployment_logs(
    account_id: str, uuid: str, offset: int | None = None, max_chars: int = 20_000
) -> JsonObject:
    """Read deployment logs; Coolify requires read:sensitive or root to return them.

    Returns the tail by default. Set offset=0 to read from the start, then follow
    next_offset. max_chars is 1..100000. Positions count characters in redacted
    text; a running deployment can append output. Commands and unrelated response
    fields are excluded; secret redaction is best effort. Missing logs are reported
    explicitly and do not mean the journal is absent on the server.
    """
    return _context.client(account_id).deployment_logs(uuid, offset=offset, max_chars=max_chars)


app = private_http_app(mcp, _private)
