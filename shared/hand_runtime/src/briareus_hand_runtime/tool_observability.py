from __future__ import annotations

import time

import mcp.types as mt
from briareus_invocation_events import InvocationEvent
from briareus_telemetry.audit_payloads import render_error, render_payload
from briareus_telemetry.observability import ObservabilitySink
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import ToolResult
from opentelemetry.trace import StatusCode

_BROWSER_SCOPES = {"web", "playwright"}
_BROWSER_SCRIPT_TOOLS = {
    "browser_type",
    "browser_evaluate",
    "browser_evaluate_script",
    "browser_run_code",
}


def _browser_arguments_payload(arguments: object, tool: str) -> str:
    if tool.startswith(("external_", "browser_external_", "devtools_")) or (
        tool in _BROWSER_SCRIPT_TOOLS
    ):
        return render_payload({"detail": "browser arguments omitted from Management audit"})
    if tool == "browser_fill":
        if not isinstance(arguments, dict):
            return render_payload({"detail": "browser input omitted from Management audit"})
        bounded = dict(arguments)
        for field in ("value", "text"):
            if field in bounded:
                bounded[field] = "<omitted>"
        return render_payload(bounded)
    return render_payload(arguments)


def _terminal_arguments_payload(arguments: object) -> str:
    if not isinstance(arguments, dict):
        return render_payload(arguments)
    bounded = dict(arguments)
    command = bounded.get("command")
    if isinstance(command, str) and len(command) > 2048:
        bounded["command"] = command[:2048] + f"<truncated {len(command) - 2048} chars>"
    data = bounded.get("data")
    if isinstance(data, str):
        bounded["data"] = f"<omitted {len(data)} chars>"
    return render_payload(bounded)


def invocation_arguments_payload(
    module: str,
    arguments: object,
    tool: str = "",
) -> str:
    normalized_module = module.strip().casefold()
    if normalized_module == "terminal" or (
        normalized_module == "server" and tool.startswith(("terminal_", "workspace_", "job_"))
    ):
        return _terminal_arguments_payload(arguments)
    if normalized_module in _BROWSER_SCOPES:
        return _browser_arguments_payload(arguments, tool)
    return render_payload(arguments)


def invocation_result_payload(module: str, result: object, tool: str = "") -> str:
    normalized_module = module.strip().casefold()
    if normalized_module == "coolify" and tool == "coolify_get_deployment_logs":
        return render_payload({"detail": "deployment logs omitted from Management audit"})
    if normalized_module == "terminal" or (
        normalized_module == "server" and tool.startswith(("terminal_", "workspace_", "job_"))
    ):
        return render_payload({"detail": "terminal result omitted from Management audit"})
    if normalized_module == "playwright" or (
        normalized_module == "web" and tool.startswith(("browser_", "external_", "devtools_"))
    ):
        return render_payload({"detail": "browser result omitted from Management audit"})
    return render_payload(result)


def management_audit_enabled(module: str, proxy_origin: str) -> bool:
    """Keep the public Analyzer call without duplicating its native backend audit."""
    return not (
        module.strip().casefold() in {"ghidra", "radare2"}
        and proxy_origin.strip().casefold() == "analysis"
    )


class ToolObservabilityMiddleware(Middleware):
    """Measure one MCP call once, then fan the observation out to configured sinks."""

    def __init__(self, module: str, sink: ObservabilitySink) -> None:
        self.module = module
        self.sink = sink
        self._browser_scope = module.strip().casefold() in _BROWSER_SCOPES

    @staticmethod
    def _account_id(context: MiddlewareContext[mt.CallToolRequestParams]) -> str:
        arguments = context.message.arguments or {}
        value = arguments.get("account_id")
        return value.strip() if isinstance(value, str) else ""

    @staticmethod
    def _request_id(context: MiddlewareContext[mt.CallToolRequestParams]) -> str:
        fastmcp_context = context.fastmcp_context
        if fastmcp_context is None or not fastmcp_context.request_context:
            return ""
        return str(fastmcp_context.request_id)

    def _submit(self, event: InvocationEvent, *, audit: bool = True) -> None:
        self.sink.record_invocation(event, audit=audit)

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        started = time.monotonic()
        account_id = self._account_id(context)
        provider = self.module if self.module in {"github", "gitlab"} else ""
        request_id = self._request_id(context)
        arguments_json = invocation_arguments_payload(
            self.module, context.message.arguments or {}, context.message.name
        )
        headers = get_http_headers()
        proxy_origin = headers.get("x-koba-proxy-origin", "").strip().casefold()
        audit = management_audit_enabled(self.module, proxy_origin)
        span_attributes: dict[str, object] = {
            "mcp.scope": self.module,
            "mcp.tool": context.message.name,
        }
        if provider:
            span_attributes["mcp.provider"] = provider
        if request_id:
            span_attributes["mcp.request.id"] = request_id
        if proxy_origin:
            span_attributes["mcp.proxy.origin"] = proxy_origin

        span_name = f"mcp.tool.{context.message.name}"
        span_context = (
            self.sink.trace_span(
                span_name, span_attributes, record_exception=False, set_status_on_exception=False
            )
            if self._browser_scope
            else self.sink.trace_span(span_name, span_attributes)
        )
        with span_context as span:
            try:
                result = await call_next(context)
            except Exception as exc:
                if self._browser_scope and span is not None:
                    span.set_status(StatusCode.ERROR, "Browser tool failed")
                    span.set_attribute("error.type", type(exc).__name__)
                event = InvocationEvent(
                    request_id=request_id,
                    module=self.module,
                    tool=context.message.name,
                    account_id=account_id,
                    provider=provider,
                    status="error",
                    duration_ms=(time.monotonic() - started) * 1000,
                    error_type=type(exc).__name__,
                    arguments_json=arguments_json,
                    error_message=(
                        "Browser tool failed; details omitted from audit"
                        if self._browser_scope
                        else render_error(exc)
                    ),
                )
                self._submit(event, audit=audit)
                raise

            self._submit(
                InvocationEvent(
                    request_id=request_id,
                    module=self.module,
                    tool=context.message.name,
                    account_id=account_id,
                    provider=provider,
                    status="success",
                    duration_ms=(time.monotonic() - started) * 1000,
                    arguments_json=arguments_json,
                    result_json=invocation_result_payload(
                        self.module, result, context.message.name
                    ),
                ),
                audit=audit,
            )
            return result
