"""Original provider tools shared by standalone and project-scoped Node runtimes."""

from __future__ import annotations

from copy import deepcopy

from common.tool_registration import ToolRegistrar
from mcp.types import CallToolResult

from common.account_contracts import AccountConnectionSummary
from common.runtime_annotations import READ_EXTERNAL
from hand_runtime.provider_schemas import JSON_OBJECT_OUTPUT_SCHEMA
from modules.coolify.metadata_views import (
    ApplicationDeployments,
    ApplicationList,
    ApplicationMetadata,
    ApplicationStorages,
    ApplicationVariables,
    CoolifyAccountSummary,
    DeploymentList,
    DeploymentMetadata,
    ServerList,
    ServerResourceList,
    TeamMetadata,
)
from modules.signoz.infrastructure.discovery import FieldKeysReply, FieldValuesReply
from modules.signoz.infrastructure.query_contracts import QueryRangeRequest
from modules.signoz.presentation.results import signoz_result

from .context import ObservabilityRuntimeContext
from .domain.sources import ProviderName
from .source_result import source_result


def register_observability_tools(
    mcp: ToolRegistrar, context: ObservabilityRuntimeContext, *, provider_native: bool = False
) -> None:
    _register_sources(mcp, context)
    _register_telemetry_reads(mcp, context, provider_native=provider_native)
    _register_infrastructure_reads(mcp, context)


def _register_sources(mcp: ToolRegistrar, context: ObservabilityRuntimeContext) -> None:
    @mcp.tool(
        title="Observability sources",
        annotations=READ_EXTERNAL,
        output_schema=deepcopy(JSON_OBJECT_OUTPUT_SCHEMA),
    )
    def observability_sources(provider: ProviderName | None = None) -> CallToolResult:
        """List configured SigNoz and Coolify sources. Use alias/id as account_id in other tools."""
        return source_result(context.sources(provider))

    @mcp.tool(title="Observability source connection", annotations=READ_EXTERNAL)
    def observability_connection(
        provider: ProviderName, account_id: str
    ) -> CoolifyAccountSummary | AccountConnectionSummary:
        """Show safe metadata for one configured source without exposing its credential."""
        if provider == "signoz":
            return context.signoz(account_id).account_summary()
        return context.coolify(account_id).account_summary()


def _register_telemetry_reads(
    mcp: ToolRegistrar, context: ObservabilityRuntimeContext, *, provider_native: bool
) -> None:
    @mcp.tool(title="Search runtime logs", annotations=READ_EXTERNAL)
    def observability_search_logs(
        account_id: str,
        start_ms: int,
        end_ms: int,
        filter_expression: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> CallToolResult:
        """Search runtime logs in a selected SigNoz source."""
        return signoz_result(
            context.signoz(account_id).search_logs(
                start_ms=start_ms,
                end_ms=end_ms,
                filter_expression=filter_expression,
                limit=limit,
                offset=offset,
            ),
            provider_native=provider_native,
        )

    @mcp.tool(title="Search traces", annotations=READ_EXTERNAL)
    def observability_search_traces(
        account_id: str,
        start_ms: int,
        end_ms: int,
        filter_expression: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> CallToolResult:
        """Search traces in a selected SigNoz source."""
        return signoz_result(
            context.signoz(account_id).search_traces(
                start_ms=start_ms,
                end_ms=end_ms,
                filter_expression=filter_expression,
                limit=limit,
                offset=offset,
            ),
            provider_native=provider_native,
        )

    @mcp.tool(title="Query telemetry", annotations=READ_EXTERNAL)
    def observability_query_telemetry(account_id: str, query: QueryRangeRequest) -> CallToolResult:
        """Run a read-only SigNoz Query Builder v5 query for logs, traces or metrics."""
        return signoz_result(
            context.signoz(account_id).query_range(query), provider_native=provider_native
        )

    @mcp.tool(title="List telemetry services", annotations=READ_EXTERNAL)
    def observability_list_services(account_id: str, start: str, end: str) -> CallToolResult:
        """List services observed by a selected SigNoz source for a time range."""
        return signoz_result(
            context.signoz(account_id).list_services(start=start, end=end),
            provider_native=provider_native,
        )

    @mcp.tool(title="Telemetry field keys", annotations=READ_EXTERNAL)
    def observability_field_keys(
        account_id: str,
        signal: str,
        search_text: str = "",
        metric_name: str = "",
    ) -> FieldKeysReply:
        """Discover available SigNoz field keys for logs, traces or metrics."""
        return context.signoz(account_id).field_keys(
            signal=signal,
            search_text=search_text,
            metric_name=metric_name,
        )

    @mcp.tool(title="Telemetry field values", annotations=READ_EXTERNAL)
    def observability_field_values(
        account_id: str,
        signal: str,
        name: str,
        search_text: str = "",
        metric_name: str = "",
    ) -> FieldValuesReply:
        """Discover values for one field in a selected SigNoz source."""
        return context.signoz(account_id).field_values(
            signal=signal,
            name=name,
            search_text=search_text,
            metric_name=metric_name,
        )


def _register_infrastructure_reads(
    mcp: ToolRegistrar, context: ObservabilityRuntimeContext
) -> None:
    @mcp.tool(title="Infrastructure team", annotations=READ_EXTERNAL)
    def observability_current_team(account_id: str) -> TeamMetadata:
        """Read the current team from a selected Coolify source."""
        return context.coolify(account_id).current_team()

    @mcp.tool(title="List infrastructure servers", annotations=READ_EXTERNAL)
    def observability_list_servers(account_id: str) -> ServerList:
        """List safe server metadata from a selected Coolify source."""
        return context.coolify(account_id).servers()

    @mcp.tool(title="List server resources", annotations=READ_EXTERNAL)
    def observability_server_resources(account_id: str, server_uuid: str) -> ServerResourceList:
        """List safe resource identity/status metadata for one Coolify server."""
        return context.coolify(account_id).server_resources(server_uuid)

    @mcp.tool(title="List infrastructure applications", annotations=READ_EXTERNAL)
    def observability_list_applications(account_id: str) -> ApplicationList:
        """List applications from a selected Coolify source."""
        return context.coolify(account_id).applications()

    @mcp.tool(title="Infrastructure application", annotations=READ_EXTERNAL)
    def observability_get_application(account_id: str, uuid: str) -> ApplicationMetadata:
        """Read one application from a selected Coolify source."""
        return context.coolify(account_id).application(uuid)

    @mcp.tool(title="Infrastructure application storages", annotations=READ_EXTERNAL)
    def observability_application_storages(
        account_id: str, application_uuid: str
    ) -> ApplicationStorages:
        """List safe Coolify storage topology without file contents or host filesystem paths."""
        return context.coolify(account_id).application_storages(application_uuid)

    @mcp.tool(title="Infrastructure application variables", annotations=READ_EXTERNAL)
    def observability_application_variables(
        account_id: str, application_uuid: str
    ) -> ApplicationVariables:
        """List safe Coolify application variable metadata; values are never returned."""
        return context.coolify(account_id).application_variables(application_uuid)

    @mcp.tool(title="List infrastructure deployments", annotations=READ_EXTERNAL)
    def observability_list_deployments(account_id: str) -> DeploymentList:
        """List deployment metadata from a selected Coolify source."""
        return context.coolify(account_id).deployments()

    @mcp.tool(title="List application deployments", annotations=READ_EXTERNAL)
    def observability_list_application_deployments(
        account_id: str,
        application_uuid: str,
    ) -> ApplicationDeployments:
        """List deployments for one application in a selected Coolify source."""
        return context.coolify(account_id).application_deployments(application_uuid)

    @mcp.tool(title="Infrastructure deployment", annotations=READ_EXTERNAL)
    def observability_get_deployment(account_id: str, uuid: str) -> DeploymentMetadata:
        """Read one deployment from a selected Coolify source."""
        return context.coolify(account_id).deployment(uuid)
