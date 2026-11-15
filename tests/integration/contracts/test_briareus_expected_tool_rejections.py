from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock, patch

import mcp.types as mt
from briareus_control_panel_client.control_panel_client import (
    AccountSelectorNotFoundError,
    ControlPanelClient,
    ControlPanelClientError,
)
from briareus_git.repository_checkout import (
    RepositoryCheckoutError,
    RepositoryDestinationError,
    checkout_destination,
)
from briareus_github.github_agent import GitHubAgentError, GitHubAppClient, GitHubRequestError
from briareus_github.github_identity import GitHubPrettyIdentityClient
from briareus_github.settings import GitHubPolicySettings
from briareus_github.tool_context import GitHubRuntimeContext
from briareus_gitlab.errors import GitLabError, GitLabRequestError
from briareus_gitlab.models import GitLabProfile
from briareus_gitlab.repository import GitLabRepositoryClient
from briareus_gitlab.settings import GitLabSettings
from briareus_gitlab.tool_context import GitLabRuntimeContext
from briareus_hand_runtime.tool_observability import ToolObservabilityMiddleware
from briareus_invocation_events import InvocationEvent
from briareus_server.terminal.manager import TerminalError
from briareus_telemetry.observability import OpenTelemetrySink
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext, MiddlewareContext
from fastmcp.tools import ToolResult
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode


class ExpectedToolRejectionContracts(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def test_checkout_rejection_keeps_mount_security_and_existing_error_compatibility(self) -> None:
        valid = checkout_destination(self.root, "projects/example/repo")
        self.assertEqual(valid, self.root / "projects/example/repo")
        for destination in (str(self.root / "projects/example/repo"), "../outside"):
            with self.subTest(destination=destination):
                with self.assertRaises(RepositoryDestinationError) as captured:
                    checkout_destination(self.root, destination)
                self.assertIsInstance(captured.exception, RepositoryCheckoutError)

    def test_github_and_gitlab_local_git_paths_are_expected_warnings(self) -> None:
        github = GitHubPrettyIdentityClient(
            account_id="public", public_only=True, auth_type="public", workspace_root=self.root
        )
        gitlab = GitLabRepositoryClient(
            GitLabProfile(
                account_id="fixture",
                alias="fixture",
                auth_type="private_token",
                base_url="https://gitlab.example.test",
            ),
            workspace_root=self.root,
            anonymous_only=True,
        )
        cases = (
            (github, GitHubRequestError, GitHubAgentError),
            (gitlab, GitLabRequestError, GitLabError),
        )
        for provider, expected, base in cases:
            with self.subTest(provider=type(provider).__name__):
                with self.assertRaises(expected) as captured:
                    provider._local_git_path(str(self.root / "projects/repository"))
                self.assertIsInstance(captured.exception, base)
                self.assertIsInstance(captured.exception, ToolError)
                self.assertEqual(captured.exception.log_level, logging.WARNING)
                self.assertIn("relative to SERVER_MOUNT_PATH", str(captured.exception))
                self.assertNotIsInstance(base("upstream unavailable"), ToolError)

                with self.assertRaises(expected) as missing:
                    provider._local_git_path("missing-checkout")
                self.assertIn("destination is not a Git checkout", str(missing.exception))

    def test_checkout_entrypoints_reject_invalid_destination_without_network(self) -> None:
        github = GitHubAppClient(token="fixture", workspace_root=self.root)
        gitlab = GitLabRepositoryClient(
            GitLabProfile(
                account_id="fixture",
                alias="fixture",
                auth_type="private_token",
                base_url="https://gitlab.example.test",
            ),
            workspace_root=self.root,
            anonymous_only=True,
        )
        for provider, expected in (
            (github, GitHubRequestError),
            (gitlab, GitLabRequestError),
        ):
            with self.subTest(provider=type(provider).__name__):
                with self.assertRaises(expected) as captured:
                    provider.checkout_repository("owner/repo", str(self.root / "absolute"))
                self.assertEqual(captured.exception.log_level, logging.WARNING)
                self.assertIn("destination must be relative", str(captured.exception))

    def test_account_alias_rejections_warn_but_transport_errors_do_not(self) -> None:
        management = MagicMock(spec=ControlPanelClient)
        github = GitHubRuntimeContext(
            cast(ControlPanelClient, management),
            GitHubPolicySettings(workspace_root=self.root),
        )
        gitlab = GitLabRuntimeContext(
            cast(ControlPanelClient, management),
            GitLabSettings(workspace_root=self.root),
        )
        for provider, select, expected in (
            ("github", github._client, GitHubRequestError),
            ("gitlab", gitlab.client, GitLabRequestError),
        ):
            with self.subTest(provider=provider):
                management.resolve_account.side_effect = AccountSelectorNotFoundError(
                    f"{provider} account selector not found: invalid; use stable alias"
                )
                with self.assertRaises(expected) as captured:
                    select("invalid")
                self.assertEqual(captured.exception.log_level, logging.WARNING)
                management.resolve_account.side_effect = ControlPanelClientError(
                    "management unavailable"
                )
                with self.assertRaises(ControlPanelClientError) as unexpected:
                    select("invalid")
                self.assertNotIsInstance(unexpected.exception, ToolError)

    async def test_fastmcp_logs_warning_while_preserving_tool_error_to_agent(self) -> None:
        app: FastMCP[None] = FastMCP("expected-failures")

        @app.tool
        def rejected_checkout() -> None:
            raise GitHubRequestError("destination must be relative to SERVER_MOUNT_PATH")

        @app.tool
        def infrastructure_error() -> None:
            raise GitHubAgentError("upstream GitHub service unavailable")

        with (
            self.assertLogs("fastmcp.server.server", level="WARNING") as logs,
            self.assertRaises(GitHubRequestError),
        ):
            await app.call_tool("rejected_checkout")
        self.assertEqual([log.levelno for log in logs.records], [logging.WARNING])
        with (
            self.assertLogs("fastmcp.server.server", level="ERROR") as logs,
            self.assertRaises(ToolError),
        ):
            await app.call_tool("infrastructure_error")
        self.assertTrue(any(log.levelno == logging.ERROR for log in logs.records))

        async with Client(app) as client:
            rejected = await client.call_tool_mcp("rejected_checkout", {})
            failed = await client.call_tool_mcp("infrastructure_error", {})
        self.assertTrue(rejected.is_error)
        self.assertIn("destination must be relative", str(rejected.content))
        self.assertTrue(failed.is_error)
        self.assertIn("upstream GitHub service unavailable", str(failed.content))


class ExpectedToolTelemetryContracts(unittest.IsolatedAsyncioTestCase):
    async def test_expected_rejection_keeps_audit_error_without_infra_span_error(self) -> None:
        provider = TracerProvider()
        exporter = InMemorySpanExporter()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        sink = object.__new__(OpenTelemetrySink)
        sink.tracer = provider.get_tracer("expected-tool-rejection-test")
        middleware = ToolObservabilityMiddleware("server", sink)
        context = MiddlewareContext(
            message=mt.CallToolRequestParams(
                name="terminal_exec", arguments={"workspace_id": "fixture", "cwd": "../"}
            )
        )

        async def rejected(_context: MiddlewareContext[mt.CallToolRequestParams]) -> ToolResult:
            raise TerminalError("cwd escapes workspace")

        try:
            with (
                patch.object(sink, "record_invocation") as record,
                patch("briareus_hand_runtime.tool_observability.get_http_headers", return_value={}),
                self.assertRaises(TerminalError),
            ):
                await middleware.on_call_tool(
                    context, cast(CallNext[mt.CallToolRequestParams, ToolResult], rejected)
                )
            event = cast(InvocationEvent, record.call_args.args[0])
            self.assertEqual(event.status, "error")
            self.assertEqual(event.error_type, "caller_rejected:TerminalError")
            self.assertIn("cwd escapes workspace", event.error_message)
            spans = exporter.get_finished_spans()
            self.assertEqual(len(spans), 1)
            self.assertEqual(spans[0].status.status_code, StatusCode.UNSET)
            self.assertEqual((spans[0].attributes or {}).get("mcp.caller_rejection"), True)
            self.assertFalse(spans[0].events)
        finally:
            provider.shutdown()

    async def test_unexpected_failure_keeps_error_span_and_audit(self) -> None:
        provider = TracerProvider()
        exporter = InMemorySpanExporter()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        sink = object.__new__(OpenTelemetrySink)
        sink.tracer = provider.get_tracer("tool-failure-test")
        middleware = ToolObservabilityMiddleware("server", sink)
        context = MiddlewareContext(message=mt.CallToolRequestParams(name="terminal_exec"))

        async def failed(_context: MiddlewareContext[mt.CallToolRequestParams]) -> ToolResult:
            raise RuntimeError("backend connection lost")

        try:
            with (
                patch.object(sink, "record_invocation") as record,
                patch("briareus_hand_runtime.tool_observability.get_http_headers", return_value={}),
                self.assertRaisesRegex(RuntimeError, "backend connection lost"),
            ):
                await middleware.on_call_tool(
                    context, cast(CallNext[mt.CallToolRequestParams, ToolResult], failed)
                )
            event = cast(InvocationEvent, record.call_args.args[0])
            self.assertEqual(event.status, "error")
            self.assertEqual(event.error_type, "RuntimeError")
            spans = exporter.get_finished_spans()
            self.assertEqual(len(spans), 1)
            self.assertEqual(spans[0].status.status_code, StatusCode.ERROR)
            self.assertEqual((spans[0].attributes or {}).get("error.type"), "RuntimeError")
            self.assertTrue(any(item.name == "exception" for item in spans[0].events))
        finally:
            provider.shutdown()

    def test_caller_rejections_separated_from_infrastructure_error_metric(self) -> None:
        sink = object.__new__(OpenTelemetrySink)
        sink.scope = "server"
        sink.tool_calls = MagicMock()
        sink.tool_duration = MagicMock()
        sink.tool_errors = MagicMock()
        sink.tool_rejections = MagicMock()
        expected = InvocationEvent(
            module="server",
            tool="terminal_exec",
            status="error",
            duration_ms=1.2,
            error_type="caller_rejected:TerminalError",
        )
        unexpected = InvocationEvent(
            module="server",
            tool="terminal_exec",
            status="error",
            duration_ms=1.3,
            error_type="RuntimeError",
        )
        sink.record_invocation(expected)
        sink.record_invocation(unexpected)
        self.assertEqual(sink.tool_calls.add.call_count, 2)
        self.assertEqual(sink.tool_rejections.add.call_count, 1)
        self.assertEqual(sink.tool_errors.add.call_count, 1)
        rejection_attrs = sink.tool_rejections.add.call_args.args[1]
        self.assertEqual(rejection_attrs["mcp.status"], "error")
        self.assertEqual(rejection_attrs["mcp.outcome"], "caller_rejected")
        self.assertEqual(rejection_attrs["error.type"], "TerminalError")
        infra_attrs = sink.tool_errors.add.call_args.args[1]
        self.assertEqual(infra_attrs["error.type"], "RuntimeError")
        self.assertNotIn("mcp.outcome", infra_attrs)
