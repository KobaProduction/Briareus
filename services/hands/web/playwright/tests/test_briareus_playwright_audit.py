import json
import unittest
from typing import cast
from unittest.mock import patch

import mcp.types as mt
from briareus_hand_runtime.tool_observability import (
    ToolObservabilityMiddleware,
    invocation_arguments_payload,
    invocation_result_payload,
)
from briareus_invocation_events import InvocationEvent
from briareus_telemetry.observability import OpenTelemetrySink
from fastmcp.server.middleware import MiddlewareContext
from fastmcp.tools import ToolResult
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode


class PlaywrightAuditContracts(unittest.IsolatedAsyncioTestCase):
    def test_fill_values_are_masked_for_current_and_legacy_browser_scopes(self) -> None:
        for module in ("playwright", "web"):
            with self.subTest(module=module):
                payload = invocation_arguments_payload(
                    module,
                    {"page_id": "page-1", "ref": "element-1", "value": "fixture-input"},
                    "browser_fill",
                )
                self.assertNotIn("fixture-input", payload)
                self.assertEqual(json.loads(payload)["value"], "<omitted>")
                self.assertEqual(json.loads(payload)["page_id"], "page-1")

    def test_external_mode_omits_all_arguments_and_results(self) -> None:
        for module in ("playwright", "web"):
            for tool in (
                "external_browser_type",
                "external_browser_fill",
                "external_browser_evaluate",
                "external_browser_run_code",
                "browser_external_connect",
            ):
                with self.subTest(module=module, tool=tool):
                    arguments = invocation_arguments_payload(
                        module, {"text": "fixture-secret", "script": "fixture-code"}, tool
                    )
                    result = invocation_result_payload(module, {"content": "fixture-page"}, tool)
                    self.assertNotIn("fixture-secret", arguments)
                    self.assertNotIn("fixture-code", arguments)
                    self.assertNotIn("fixture-page", result)

    def test_internal_type_and_evaluate_arguments_are_not_audited(self) -> None:
        for tool in ("browser_type", "browser_evaluate", "browser_run_code"):
            with self.subTest(tool=tool):
                payload = invocation_arguments_payload(
                    "playwright", {"text": "fixture-input", "function": "fixture-script"}, tool
                )
                self.assertNotIn("fixture-input", payload)
                self.assertNotIn("fixture-script", payload)

    async def test_browser_page_results_are_not_audited(self) -> None:
        for tool in ("browser_snapshot", "browser_open", "browser_evaluate", "future_browser_tool"):
            with self.subTest(tool=tool):
                payload = invocation_result_payload("playwright", {"content": "fixture-page"}, tool)
                self.assertNotIn("fixture-page", payload)
                self.assertIn("omitted", payload)

        fixture = "fixture-private-browser-error"
        provider = TracerProvider()
        exporter = InMemorySpanExporter()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        sink = object.__new__(OpenTelemetrySink)
        sink.tracer = provider.get_tracer("browser-audit-contract")
        context = MiddlewareContext(
            message=mt.CallToolRequestParams(
                name="external_browser_evaluate", arguments={"function": fixture}
            )
        )

        async def failed_call(context: MiddlewareContext[mt.CallToolRequestParams]) -> ToolResult:
            del context
            raise RuntimeError(fixture)

        try:
            with (
                patch.object(sink, "record_invocation") as record,
                patch("briareus_hand_runtime.tool_observability.get_http_headers", return_value={}),
            ):
                middleware = ToolObservabilityMiddleware("playwright", sink)
                with self.assertRaisesRegex(RuntimeError, fixture):
                    await middleware.on_call_tool(context, failed_call)
                event = cast(InvocationEvent, record.call_args.args[0])
                self.assertEqual(event.error_type, "RuntimeError")
                self.assertNotIn(fixture, event.error_message)
                self.assertNotIn(fixture, event.arguments_json)
            span = exporter.get_finished_spans()[0]
            self.assertEqual(span.status.status_code, StatusCode.ERROR)
            self.assertEqual(span.status.description, "Browser tool failed")
            self.assertEqual((span.attributes or {}).get("error.type"), "RuntimeError")
            self.assertFalse(span.events)
            with (
                self.assertRaisesRegex(ValueError, "fixture-default-error"),
                sink.trace_span("ordinary-default-flags"),
            ):
                raise ValueError("fixture-default-error")
            ordinary = exporter.get_finished_spans()[1]
            self.assertTrue(any(event.name == "exception" for event in ordinary.events))
            self.assertIn("fixture-default-error", ordinary.status.description or "")
        finally:
            provider.shutdown()
