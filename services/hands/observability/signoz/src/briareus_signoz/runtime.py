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

from briareus_signoz.client import SigNozClient

_private = PrivateRuntimeSettings()
_management = management_client(ControlPanelClientSettings())
_context = ProviderClientCache(_management, "signoz", SigNozClient)
mcp = build_private_mcp("signoz", _management)


@mcp.tool(title="SigNoz sources", annotations=READ_EXTERNAL)
def signoz_sources() -> JsonObject:
    """List configured SigNoz sources without exposing credentials."""
    return _context.sources().model_dump(mode="json")


@mcp.tool(title="SigNoz connection", annotations=READ_EXTERNAL)
def signoz_connection(account_id: str) -> JsonObject:
    """Show safe metadata for one configured SigNoz source."""
    return _context.client(account_id).account_summary()


@mcp.tool(title="Search runtime logs", annotations=READ_EXTERNAL)
def signoz_search_logs(
    account_id: str,
    start_ms: int,
    end_ms: int,
    filter_expression: str = "",
    limit: int = 100,
    offset: int = 0,
) -> JsonValue:
    """Search runtime logs in a selected SigNoz source."""
    return _context.client(account_id).search_logs(
        start_ms=start_ms,
        end_ms=end_ms,
        filter_expression=filter_expression,
        limit=limit,
        offset=offset,
    )


@mcp.tool(title="Search traces", annotations=READ_EXTERNAL)
def signoz_search_traces(
    account_id: str,
    start_ms: int,
    end_ms: int,
    filter_expression: str = "",
    limit: int = 100,
    offset: int = 0,
) -> JsonValue:
    """Search traces in a selected SigNoz source."""
    return _context.client(account_id).search_traces(
        start_ms=start_ms,
        end_ms=end_ms,
        filter_expression=filter_expression,
        limit=limit,
        offset=offset,
    )


@mcp.tool(title="Query telemetry", annotations=READ_EXTERNAL)
def signoz_query_telemetry(account_id: str, query: JsonObject) -> JsonValue:
    """Run a read-only SigNoz Query Builder v5 query for logs, traces or metrics."""
    return _context.client(account_id).query_range(query)


@mcp.tool(title="List telemetry services", annotations=READ_EXTERNAL)
def signoz_list_services(account_id: str, start: str, end: str) -> JsonValue:
    """List services observed by a selected SigNoz source for a time range."""
    return _context.client(account_id).list_services(start=start, end=end)


@mcp.tool(title="Telemetry field keys", annotations=READ_EXTERNAL)
def signoz_field_keys(
    account_id: str,
    signal: str,
    search_text: str = "",
    metric_name: str = "",
) -> JsonValue:
    """Discover available SigNoz field keys for logs, traces or metrics."""
    return _context.client(account_id).field_keys(
        signal=signal,
        search_text=search_text,
        metric_name=metric_name,
    )


@mcp.tool(title="Telemetry field values", annotations=READ_EXTERNAL)
def signoz_field_values(
    account_id: str,
    signal: str,
    name: str,
    search_text: str = "",
    metric_name: str = "",
) -> JsonValue:
    """Discover values for one field in a selected SigNoz source."""
    return _context.client(account_id).field_values(
        signal=signal,
        name=name,
        search_text=search_text,
        metric_name=metric_name,
    )


app = private_http_app(mcp, _private)
