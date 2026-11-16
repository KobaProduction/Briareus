from __future__ import annotations

from pathlib import Path

from briareus_control_panel_client.settings import ControlPanelClientSettings
from briareus_hand_runtime import ProviderClientCache
from briareus_hand_runtime.hand_workflows import hand_version, register_hand_workflow
from briareus_hand_runtime.runtime_common import (
    build_private_mcp,
    management_client,
    private_http_app,
)
from briareus_hand_runtime.settings import PrivateRuntimeSettings
from briareus_json_values import JsonObject, JsonValue
from briareus_tool_annotations import READ_EXTERNAL, WRITE_EXTERNAL

from briareus_coolify.client import CoolifyClient

_private = PrivateRuntimeSettings()
_management = management_client(ControlPanelClientSettings())
_context = ProviderClientCache(_management, "coolify", CoolifyClient)
_source_root = Path(__file__).resolve().parent
mcp = build_private_mcp(
    "coolify",
    _management,
    instructions=(
        "Before Coolify infrastructure, Compose or deployment tasks, read "
        "skill://coolify-deployment-workflow/SKILL.md and "
        "skill://ai-agent-services-deployment/SKILL.md when available. "
        "Read mandatory source rules for the task, inspect actual resource state "
        "and permissions; deployment requests need explicit authorization."
    ),
    version=hand_version(_source_root, shared_deployment=True),
)
register_hand_workflow(
    mcp, _source_root, "coolify-deployment-workflow", shared_deployment=True
)


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


@mcp.tool(title="List Coolify services", annotations=READ_EXTERNAL)
def coolify_list_services(account_id: str) -> JsonValue:
    """List safe service identity/status; never expose rendered Docker Compose or secrets."""
    return _context.client(account_id).services()


@mcp.tool(title="Get Coolify service", annotations=READ_EXTERNAL)
def coolify_get_service(account_id: str, service_uuid: str) -> JsonObject:
    """Read safe service metadata and component names for scoped log selection."""
    return _context.client(account_id).service(service_uuid)


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


@mcp.tool(title="Shared variable status and masked preview", annotations=READ_EXTERNAL)
def coolify_shared_variables(
    account_id: str,
    scope: str,
    project_uuid: str = "",
    environment_uuid: str = "",
    server_uuid: str = "",
    mode: str = "status",
) -> JsonObject:
    """Show presence and length of shared variables at one explicit scope.

    mode=status (default) returns no value characters. mode=masked reveals at
    most first two and last two characters when at least eight are available;
    the entire secret remains hidden for shorter values. Neither mode ever
    returns a full shared value. Coolify read:sensitive and sufficient resource
    scope are required to calculate actual lengths/previews; unknown remains
    unknown when Coolify locks or redacts a variable. Team/server scopes may be
    unavailable for Coolify tokens restricted to selected resources.
    """
    if mode not in {"status", "masked"}:
        raise ValueError("mode must be status or masked")
    return _context.client(account_id).shared_variables(
        scope,
        project_uuid=project_uuid,
        environment_uuid=environment_uuid,
        server_uuid=server_uuid,
        masked=mode == "masked",
    )


@mcp.tool(title="Prepare scoped application variable read", annotations=READ_EXTERNAL)
def coolify_prepare_application_variable_read(
    account_id: str, application_uuid: str, key: str
) -> JsonObject:
    """Stage a read of ONE application variable. Does not reveal its value.

    Before making this call, verify that the intended operator authorizes access
    to this specific application's sensitive configuration. A separate confirm
    tool call with one-use challenge, true permission assertion and specific
    purpose is required. Locked variables and Shared references cannot be read.
    """
    return _context.client(account_id).prepare_application_variable_read(application_uuid, key)


@mcp.tool(title="Confirm application variable value read", annotations=READ_EXTERNAL)
def coolify_confirm_application_variable_read(
    account_id: str,
    application_uuid: str,
    key: str,
    confirmation_token: str,
    permission_confirmed: bool,
    purpose: str,
) -> JsonObject:
    """Return ONE application variable only after a separate confirmed MCP call.

    The confirmation asserts that the caller independently verified permission
    from the operator for this particular value. It is not a substitute for
    Coolify token read:sensitive privileges or operator approval. One-use
    challenges expire after two minutes; no Shared, Shared references or locked
    variables may be exposed, even by confirmation. Do not echo the value in
    chat, logs or another tool unless the operator explicitly needs it.
    """
    return _context.client(account_id).confirm_application_variable_read(
        application_uuid,
        key,
        confirmation_token=confirmation_token,
        permission_confirmed=permission_confirmed,
        purpose=purpose,
    )


@mcp.tool(title="Coolify application runtime logs", annotations=READ_EXTERNAL)
def coolify_get_application_logs(
    account_id: str,
    application_uuid: str,
    lines: int = 200,
    service_name: str = "",
    show_timestamps: bool = True,
    offset: int | None = None,
    max_chars: int = 20_000,
) -> JsonObject:
    """Read bounded REDACTED container runtime logs from a selected application.

    Requires Coolify read:sensitive (or root) for /applications/{uuid}/logs.
    For Compose applications, service_name selects one service container.
    This differs from build/deployment journal logs. Results are omitted from
    Control Panel audit; redaction is best effort and may not catch arbitrary
    application-defined credentials. Do not request logs outside approved scope.
    """
    return _context.client(account_id).application_logs(
        application_uuid,
        lines=lines,
        service_name=service_name,
        show_timestamps=show_timestamps,
        offset=offset,
        max_chars=max_chars,
    )


@mcp.tool(title="Coolify service runtime logs", annotations=READ_EXTERNAL)
def coolify_get_service_logs(
    account_id: str,
    service_uuid: str,
    sub_service_name: str,
    lines: int = 200,
    show_timestamps: bool = True,
    offset: int | None = None,
    max_chars: int = 20_000,
) -> JsonObject:
    """Read bounded redacted logs of one component of a Coolify Service.

    Requires read:sensitive for /services/{uuid}/logs. sub_service_name is the
    exact component name from coolify_get_service, not a Docker container ID.
    Result is omitted from tool-call audit; arbitrary secrets may evade the
    best-effort log redaction.
    """
    return _context.client(account_id).service_logs(
        service_uuid, sub_service_name,
        lines=lines,
        show_timestamps=show_timestamps,
        offset=offset,
        max_chars=max_chars,
    )


@mcp.tool(title="Restart one Coolify application", annotations=WRITE_EXTERNAL)
def coolify_restart_application(
    account_id: str, application_uuid: str, confirm: bool = False
) -> JsonObject:
    """Request an application/container restart after explicit confirm=true.

    Requires Coolify deploy permission and operator authorization for the exact
    resource. This does NOT reboot the physical host or affect other apps.
    Returns the upstream queued request, not proof of a healthy restart.
    """
    return _context.client(account_id).restart_application(application_uuid, confirm=confirm)


@mcp.tool(title="Restart one Coolify service", annotations=WRITE_EXTERNAL)
def coolify_restart_service(
    account_id: str,
    service_uuid: str,
    confirm: bool = False,
    pull_latest: bool = False,
) -> JsonObject:
    """Queue restart of one Coolify service resource, not a physical server.

    Requires Coolify deploy permission, the precise resource UUID and
    confirm=True after operator authorization. pull_latest defaults to false.
    """
    return _context.client(account_id).restart_service(
        service_uuid, confirm=confirm, pull_latest=pull_latest
    )


@mcp.tool(title="Deploy one Coolify application", annotations=WRITE_EXTERNAL)
def coolify_deploy_application(
    account_id: str,
    application_uuid: str,
    confirm: bool = False,
    force_rebuild: bool = False,
) -> JsonObject:
    """Request a single-application deployment after explicit confirm=true.

    Requires Coolify deploy permission and operator authorization for the exact
    resource. force_rebuild bypasses the build cache and defaults to false.
    Does not update source, secrets or all resources in a project. A queued
    deployment is not evidence that build/health/consumer acceptance succeeded.
    """
    return _context.client(account_id).deploy_application(
        application_uuid, confirm=confirm, force_rebuild=force_rebuild
    )


@mcp.tool(title="Deploy one Coolify service", annotations=WRITE_EXTERNAL)
def coolify_deploy_service(
    account_id: str,
    service_uuid: str,
    confirm: bool = False,
    force_rebuild: bool = False,
) -> JsonObject:
    """Queue deployment of exactly one Coolify Service with explicit confirm=true.

    Requires the provider deploy permission and authority for this service.
    This does not operate on physical servers or all team resources.
    """
    return _context.client(account_id).deploy_service(
        service_uuid, confirm=confirm, force_rebuild=force_rebuild
    )


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
