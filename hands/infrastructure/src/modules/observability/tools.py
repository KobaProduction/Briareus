"""Original provider tools shared by standalone and project-scoped Node runtimes."""
from __future__ import annotations
from common.models import JsonObject, JsonValue
from common.runtime_annotations import READ_EXTERNAL
from .context import ObservabilityRuntimeContext, ProviderName


def register_observability_tools(mcp, context: ObservabilityRuntimeContext) -> None:
    @mcp.tool(title="Observability sources", annotations=READ_EXTERNAL)
    def observability_sources(provider: ProviderName | None = None) -> JsonObject:
        """List configured SigNoz and Coolify sources. Use alias/id as account_id in other tools."""
        return context.sources(provider)


    @mcp.tool(title="Observability source connection", annotations=READ_EXTERNAL)
    def observability_connection(provider: ProviderName, account_id: str) -> JsonObject:
        """Show safe metadata for one configured source without exposing its credential."""
        if provider == "signoz":
            return context.signoz(account_id).account_summary()
        return context.coolify(account_id).account_summary()


    @mcp.tool(title="Search runtime logs", annotations=READ_EXTERNAL)
    def observability_search_logs(
        account_id: str,
        start_ms: int,
        end_ms: int,
        filter_expression: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> JsonValue:
        """Search runtime logs in a selected SigNoz source."""
        return context.signoz(account_id).search_logs(
            start_ms=start_ms,
            end_ms=end_ms,
            filter_expression=filter_expression,
            limit=limit,
            offset=offset,
        )


    @mcp.tool(title="Search traces", annotations=READ_EXTERNAL)
    def observability_search_traces(
        account_id: str,
        start_ms: int,
        end_ms: int,
        filter_expression: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> JsonValue:
        """Search traces in a selected SigNoz source."""
        return context.signoz(account_id).search_traces(
            start_ms=start_ms,
            end_ms=end_ms,
            filter_expression=filter_expression,
            limit=limit,
            offset=offset,
        )


    @mcp.tool(title="Query telemetry", annotations=READ_EXTERNAL)
    def observability_query_telemetry(account_id: str, query: JsonObject) -> JsonValue:
        """Run a read-only SigNoz Query Builder v5 query for logs, traces or metrics."""
        return context.signoz(account_id).query_range(query)


    @mcp.tool(title="List telemetry services", annotations=READ_EXTERNAL)
    def observability_list_services(account_id: str, start: str, end: str) -> JsonValue:
        """List services observed by a selected SigNoz source for a time range."""
        return context.signoz(account_id).list_services(start=start, end=end)


    @mcp.tool(title="Telemetry field keys", annotations=READ_EXTERNAL)
    def observability_field_keys(
        account_id: str,
        signal: str,
        search_text: str = "",
        metric_name: str = "",
    ) -> JsonValue:
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
    ) -> JsonValue:
        """Discover values for one field in a selected SigNoz source."""
        return context.signoz(account_id).field_values(
            signal=signal,
            name=name,
            search_text=search_text,
            metric_name=metric_name,
        )


    @mcp.tool(title="Infrastructure team", annotations=READ_EXTERNAL)
    def observability_current_team(account_id: str) -> JsonObject:
        """Read the current team from a selected Coolify source."""
        return context.coolify(account_id).current_team()


    @mcp.tool(title="List infrastructure servers", annotations=READ_EXTERNAL)
    def observability_list_servers(account_id: str) -> JsonValue:
        """List safe server metadata from a selected Coolify source."""
        return context.coolify(account_id).servers()


    @mcp.tool(title="List server resources", annotations=READ_EXTERNAL)
    def observability_server_resources(account_id: str, server_uuid: str) -> JsonValue:
        """List safe resource identity/status metadata for one Coolify server."""
        return context.coolify(account_id).server_resources(server_uuid)


    @mcp.tool(title="List infrastructure applications", annotations=READ_EXTERNAL)
    def observability_list_applications(account_id: str) -> JsonValue:
        """List applications from a selected Coolify source."""
        return context.coolify(account_id).applications()


    @mcp.tool(title="Infrastructure application", annotations=READ_EXTERNAL)
    def observability_get_application(account_id: str, uuid: str) -> JsonObject:
        """Read one application from a selected Coolify source."""
        return context.coolify(account_id).application(uuid)


    @mcp.tool(title="Infrastructure application storages", annotations=READ_EXTERNAL)
    def observability_application_storages(account_id: str, application_uuid: str) -> JsonObject:
        """List safe Coolify storage topology without file contents or host filesystem paths."""
        return context.coolify(account_id).application_storages(application_uuid)


    @mcp.tool(title="Infrastructure application variables", annotations=READ_EXTERNAL)
    def observability_application_variables(account_id: str, application_uuid: str) -> JsonObject:
        """List safe Coolify application variable metadata; values are never returned."""
        return context.coolify(account_id).application_variables(application_uuid)


    @mcp.tool(title="List infrastructure deployments", annotations=READ_EXTERNAL)
    def observability_list_deployments(account_id: str) -> JsonValue:
        """List deployment metadata from a selected Coolify source."""
        return context.coolify(account_id).deployments()


    @mcp.tool(title="List application deployments", annotations=READ_EXTERNAL)
    def observability_list_application_deployments(
        account_id: str,
        application_uuid: str,
    ) -> JsonValue:
        """List deployments for one application in a selected Coolify source."""
        return context.coolify(account_id).application_deployments(application_uuid)


    @mcp.tool(title="Infrastructure deployment", annotations=READ_EXTERNAL)
    def observability_get_deployment(account_id: str, uuid: str) -> JsonObject:
        """Read one deployment from a selected Coolify source."""
        return context.coolify(account_id).deployment(uuid)


