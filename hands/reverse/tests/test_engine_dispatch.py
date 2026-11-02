"""Engine selection and cancellation preserve the unified private execution boundary."""

import asyncio
import io
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4

from fastmcp.client.client import CallToolResult as ClientToolResult
from fastmcp.tools import FunctionTool, Tool
from mcp.types import CallToolRequestParams, CallToolResult, TextContent
from pydantic import BaseModel, JsonValue
from reverse_hand.application.dispatch import RejectedResult
from reverse_hand.domain.dispatch import Engine, EngineCommand
from reverse_hand.infrastructure.analysis_requests import (
    CurrentAnalysisCall,
    current_request,
    engine_invocation,
)
from reverse_hand.infrastructure.child_io import serve_requests
from reverse_hand.infrastructure.engine_dispatch import (
    AnalysisIngress,
    EngineClient,
    McpEngineExecution,
    NativeDeadline,
    engine_catalogue,
)
from reverse_hand.infrastructure.engine_storage import prepare_storage

from hand_runtime.analysis_call import AnalysisCommand


def native_fixture() -> str:
    return "native content"


@dataclass
class ClientFixture:
    calls: list[CallToolRequestParams] = field(default_factory=list)
    error: BaseException | None = None

    async def call_tool(
        self, name: str, arguments: dict[str, object], *, raise_on_error: bool
    ) -> ClientToolResult:
        if raise_on_error:
            raise AssertionError("SDK errors must remain in the result")
        self.calls.append(CallToolRequestParams(name=name, arguments=arguments))
        if self.error is not None:
            raise self.error
        return ClientToolResult(
            content=[TextContent(type="text", text="native content")],
            structured_content={"native": True},
            meta=None,
            is_error=False,
        )


@dataclass
class EngineFixture:
    client: ClientFixture = field(default_factory=ClientFixture)
    deadline: NativeDeadline = field(default_factory=NativeDeadline)
    tools: dict[Engine, tuple[Tool, ...]] = field(
        default_factory=lambda: {
            "ghidra": (FunctionTool.from_function(native_fixture, name="import_file"),),
            "radare2": (FunctionTool.from_function(native_fixture, name="radare2_functions"),),
        }
    )

    def execution(self) -> McpEngineExecution:
        clients: dict[Engine, EngineClient] = {
            "ghidra": self.client,
            "radare2": self.client,
        }
        return McpEngineExecution(clients, self.deadline, self.tools)

    def ingress(self) -> AnalysisIngress:
        return AnalysisIngress(
            {engine: engine_catalogue(engine, tools) for engine, tools in self.tools.items()},
            self.execution(),
            lambda: 100,
            None,
        )


class RpcReply(BaseModel):
    id: UUID
    result: CallToolResult


class CatalogueTool(BaseModel):
    name: str
    inputSchema: dict[str, JsonValue]


class CataloguePayload(BaseModel):
    engine: Engine
    tools: tuple[CatalogueTool, ...]


class RequestPolicyTests(unittest.TestCase):
    def test_exact_current_request_requires_v4_and_original_five_second_window(self) -> None:
        command = AnalysisCommand(
            id=uuid4(),
            expires_at=105,
            call=CallToolRequestParams(name="analysis_call", arguments={}),
        )
        raw = command.encode()
        request = current_request(raw, frozenset({"analysis_call"}), 100, runtime_ready=True)
        self.assertEqual(request.expires_at, 105)
        for expiry in ("100", "106", "true", "105.0"):
            with self.subTest(expiry=expiry), self.assertRaises(ValueError):
                current_request(
                    raw.replace(b'"expires_at": 105', ('"expires_at": ' + expiry).encode()),
                    frozenset({"analysis_call"}),
                    100,
                    runtime_ready=True,
                )
        with self.assertRaises(ValueError):
            current_request(
                raw.replace(str(command.id).encode(), b"00000000-0000-0000-0000-000000000000"),
                frozenset({"analysis_call"}),
                100,
                runtime_ready=True,
            )

    def test_stopped_runtime_or_unknown_facade_tool_cannot_dispatch(self) -> None:
        raw = AnalysisCommand(
            id=uuid4(),
            expires_at=105,
            call=CallToolRequestParams(name="analysis_call", arguments={}),
        ).encode()
        with self.assertRaises(ValueError):
            current_request(raw, frozenset({"analysis_call"}), 100, runtime_ready=False)
        with self.assertRaises(ValueError):
            current_request(raw, frozenset(), 100, runtime_ready=True)
        with self.assertRaises(ValueError):
            current_request(
                b'{"extra":true,' + raw.lstrip()[1:],
                frozenset({"analysis_call"}),
                100,
                runtime_ready=True,
            )


class DispatchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.fixture = EngineFixture()
        self.dispatch = self.fixture.ingress()

    @staticmethod
    def request(call: CallToolRequestParams) -> CurrentAnalysisCall:
        return CurrentAnalysisCall(uuid4(), 105, call)

    async def test_each_catalogue_exposes_only_its_real_engine_tools_without_execution(
        self,
    ) -> None:
        for engine, tools in self.fixture.tools.items():
            with self.subTest(engine=engine):
                result = await self.dispatch.execute(
                    self.request(
                        CallToolRequestParams(name="analysis_tools", arguments={"engine": engine})
                    )
                )
                self.assertIsInstance(result, CallToolResult)
                assert isinstance(result, CallToolResult)
                payload = CataloguePayload.model_validate(result.structured_content)
                self.assertEqual(payload.engine, engine)
                self.assertEqual(
                    tuple(tool.name for tool in payload.tools), tuple(tool.name for tool in tools)
                )
        self.assertEqual(self.fixture.client.calls, [])

    async def test_unknown_cross_engine_and_extra_arguments_never_invoke_native_tools(self) -> None:
        invalid = (
            CallToolRequestParams(
                name="analysis_call",
                arguments={"engine": "unknown", "tool": "import_file", "arguments": {}},
            ),
            CallToolRequestParams(
                name="analysis_call",
                arguments={"engine": "ghidra", "tool": "radare2_functions", "arguments": {}},
            ),
            CallToolRequestParams(
                name="analysis_call",
                arguments={
                    "engine": "radare2",
                    "tool": "radare2_functions",
                    "arguments": {},
                    "extra": True,
                },
            ),
            CallToolRequestParams(
                name="analysis_call",
                arguments={"engine": "radare2", "tool": "radare2_functions", "arguments": []},
            ),
        )
        for call in invalid:
            with self.subTest(call=call):
                self.assertIsInstance(
                    await self.dispatch.execute(self.request(call)), RejectedResult
                )
        self.assertEqual(self.fixture.client.calls, [])

    async def test_current_call_deadline_and_long_operation_parent_lease_remain_distinct(
        self,
    ) -> None:
        for tool, deadline in (("analysis_call", 105), ("analysis_start", None)):
            result = await self.dispatch.execute(
                self.request(
                    CallToolRequestParams(
                        name=tool,
                        arguments={
                            "engine": "radare2",
                            "tool": "radare2_functions",
                            "arguments": {"binary_id": "binary"},
                        },
                    )
                )
            )
            assert isinstance(result, CallToolResult)
            self.assertEqual(result.structured_content, {"native": True})
            self.assertEqual(self.fixture.deadline.expires_at, deadline)

    async def test_native_diagnostic_is_not_exposed(self) -> None:
        self.fixture.client.error = ValueError("private file path")
        result = await self.dispatch.execute(
            self.request(
                CallToolRequestParams(
                    name="analysis_call",
                    arguments={"engine": "ghidra", "tool": "import_file", "arguments": {}},
                )
            )
        )
        self.assertIsInstance(result, RejectedResult)
        self.assertNotIn("private file path", repr(result))

    async def test_timeout_and_cancellation_escape_for_parent_cohort_cleanup(self) -> None:
        call = CallToolRequestParams(
            name="analysis_call",
            arguments={"engine": "ghidra", "tool": "import_file", "arguments": {}},
        )
        for error in (TimeoutError(), asyncio.CancelledError()):
            self.fixture.client.error = error
            with self.subTest(error=type(error).__name__), self.assertRaises(type(error)):
                await self.dispatch.execute(self.request(call))

    async def wire(self, call: CallToolRequestParams) -> str:
        raw = AnalysisCommand(id=uuid4(), expires_at=105, call=call).encode()
        output = io.StringIO()
        with (
            patch("sys.stdin", SimpleNamespace(buffer=io.BytesIO(raw))),
            patch("sys.stdout", output),
            patch("reverse_hand.infrastructure.child_io.time.time", return_value=100),
        ):
            await serve_requests(self.dispatch, frozenset({"analysis_tools"}), lambda: True)
        return output.getvalue()

    async def test_wire_result_preserves_aliases_and_rejection_omits_structured_content(
        self,
    ) -> None:
        wire = await self.wire(
            CallToolRequestParams(name="analysis_tools", arguments={"engine": "ghidra"})
        )
        reply = RpcReply.model_validate_json(wire)
        self.assertFalse(reply.result.is_error)
        payload = CataloguePayload.model_validate(reply.result.structured_content)
        self.assertEqual(payload.tools[0].inputSchema, self.fixture.tools["ghidra"][0].parameters)
        self.assertIn('"structuredContent"', wire)
        self.assertIn('"isError"', wire)
        rejected = await self.wire(
            CallToolRequestParams(name="analysis_tools", arguments={"engine": "unknown"})
        )
        self.assertTrue(RpcReply.model_validate_json(rejected).result.is_error)
        self.assertNotIn('"structuredContent"', rejected)


class NativeAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_engine_adapter_sets_current_native_deadline_and_preserves_content_aliases(
        self,
    ) -> None:
        fixture = EngineFixture()
        invocation = engine_invocation(
            CallToolRequestParams(
                name="analysis_call",
                arguments={
                    "engine": "radare2",
                    "tool": "radare2_functions",
                    "arguments": {"binary_id": "binary"},
                },
            )
        )
        adapter = fixture.execution().bind(invocation)
        for expiry in (105, None):
            result = await adapter.invoke(invocation.command, expiry)
            self.assertEqual(fixture.deadline.expires_at, expiry)
            self.assertEqual(result.structured_content, {"native": True})
            self.assertEqual(fixture.client.calls[-1], invocation.call)
        with self.assertRaises(ValueError):
            await adapter.invoke(EngineCommand("ghidra", None), 105)

    async def test_stdio_adapter_correlates_response_and_stops_at_eof(self) -> None:
        identity = uuid4()
        raw = AnalysisCommand(
            id=identity,
            expires_at=105,
            call=CallToolRequestParams(name="analysis_tools", arguments={"engine": "ghidra"}),
        ).encode()
        fixture = EngineFixture()
        output = io.StringIO()
        with (
            patch("sys.stdin", SimpleNamespace(buffer=io.BytesIO(raw))),
            patch("sys.stdout", output),
            patch("reverse_hand.infrastructure.child_io.time.time", return_value=100),
        ):
            await serve_requests(fixture.ingress(), frozenset({"analysis_tools"}), lambda: True)
        reply = RpcReply.model_validate_json(output.getvalue())
        self.assertEqual(reply.id, identity)
        self.assertEqual(
            CataloguePayload.model_validate(reply.result.structured_content).engine, "ghidra"
        )
        self.assertEqual(fixture.client.calls, [])

    async def test_stdio_adapter_rejects_oversize_before_engine_execution(self) -> None:
        fixture = EngineFixture()
        with (
            patch("sys.stdin", SimpleNamespace(buffer=io.BytesIO(b"x" * 32769))),
            self.assertRaises(ValueError),
        ):
            await serve_requests(fixture.ingress(), frozenset(), lambda: True)
        self.assertEqual(fixture.client.calls, [])

    def test_engine_storage_has_separate_paths_and_cannot_use_a_regular_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = prepare_storage(Path(directory))
            self.assertNotEqual(storage.ghidra, storage.radare2)
            self.assertTrue(storage.ghidra.is_dir())
            self.assertTrue(storage.radare2.is_dir())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ghidra").write_text("not storage")
            with self.assertRaises(OSError):
                prepare_storage(root)
