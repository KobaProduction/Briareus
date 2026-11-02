"""IPC reuses original callable signatures without starting another MCP SDK."""
import subprocess
import sys
import unittest
from dataclasses import replace
from typing import NamedTuple

from mcp.types import CallToolRequestParams
from modules.terminal.dispatch import TerminalToolDispatch
from pydantic import ValidationError

from modules.terminal.manager import TerminalManager
from node_protocol.terminal import TOOLS
from runtime_peer.terminal_receipts import JobExecution, JobStatus


class ExecutionCall(NamedTuple):
    workspace_id: str
    command: str
    cwd: str
    env: dict[str, str] | None
    timeout_seconds: float | None
    max_output_bytes: int | None

class RecordingManager(TerminalManager):
    def __init__(self) -> None:
        self.exec_calls: list[ExecutionCall] = []
        self.cancel_calls: list[tuple[str, float]] = []
        self.receipt = JobExecution(
            job_id="owned", workspace_id="team", label="", command="printf ok", cwd="",
            interactive=False, state="completed", pid=None, exit_code=0, signal=None,
            created_at=None, started_at=None, ended_at=None, duration_seconds=0,
            output_bytes=2, output_truncated=False, timeout_seconds=None,
            stdout="ok", stderr="", output="ok", output_stream="combined", next_cursor=2,
            eof=True, stdout_truncated=False, stderr_truncated=False, timed_out=False,
        )

    async def terminal_exec(
        self, workspace_id: str, command: str, cwd: str = "",
        env: dict[str, str] | None = None, timeout_seconds: float | None = None,
        max_output_bytes: int | None = None,
    ) -> JobExecution:
        self.exec_calls.append(ExecutionCall(
            workspace_id, command, cwd, env, timeout_seconds, max_output_bytes,
        ))
        return self.receipt

    async def job_cancel(self, job_id: str, grace_seconds: float = 3) -> JobStatus:
        self.cancel_calls.append((job_id, grace_seconds))
        return replace(self.receipt, state="cancelled")


class ToolDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_bounds_are_validated_before_manager_and_exposed_to_agents(self) -> None:
        from fastmcp import FastMCP

        from modules.terminal.tools import register_terminal_tools

        manager = RecordingManager()
        dispatch = TerminalToolDispatch(manager)
        for invalid in (0, -1, 3.1, False, float("nan"), float("inf")):
            with self.assertRaises(ValidationError):
                await dispatch.call(CallToolRequestParams(
                    name="job_cancel", arguments={"job_id": "owned", "grace_seconds": invalid},
                ))
        self.assertEqual(manager.cancel_calls, [])
        await dispatch.call(CallToolRequestParams(
            name="job_cancel", arguments={"job_id": "owned", "grace_seconds": 0.5},
        ))
        self.assertEqual(manager.cancel_calls, [("owned", 0.5)])
        mcp: FastMCP[None] = FastMCP("schema")
        register_terminal_tools(mcp, manager)
        tool = await mcp.get_tool("job_cancel")
        assert tool is not None
        parameter = tool.parameters["properties"]["grace_seconds"]
        self.assertEqual(parameter["exclusiveMinimum"], 0)
        self.assertEqual(parameter["maximum"], 3)

    async def test_known_tools_typed_defaults_and_no_unvalidated_command(self) -> None:
        manager = RecordingManager()
        dispatch = TerminalToolDispatch(manager)
        self.assertEqual(set(dispatch.tools), TOOLS)
        result = await dispatch.call(CallToolRequestParams(
            name="terminal_exec", arguments={"workspace_id": "team", "command": "printf ok"},
        ))
        self.assertIs(result, manager.receipt)
        self.assertEqual(manager.exec_calls, [
            ExecutionCall("team", "printf ok", "", None, None, None),
        ])
        for invalid in (
            {"workspace_id": "team", "command": ["bad"]},
            {"workspace_id": "team", "command": "bad", "escape": True},
            {"workspace_id": "team", "command": "bad", "timeout_seconds": "3"},
        ):
            with self.assertRaises(ValidationError):
                await dispatch.call(CallToolRequestParams(name="terminal_exec", arguments=invalid))
        with self.assertRaises(KeyError):
            await dispatch.call(CallToolRequestParams(
                name="__getattribute__", arguments={"name": "settings"},
            ))
        self.assertEqual(len(manager.exec_calls), 1)

    def test_child_dispatch_import_has_no_runtime_side_effects(self) -> None:
        probe = (
            "from unittest.mock import patch; "
            "from contextlib import ExitStack; "
            "guards = ['subprocess.Popen', 'socket.socket.connect', "
            "'socket.socket.connect_ex', 'socket.create_connection']; "
            "stack = ExitStack(); "
            "[stack.enter_context(patch(name, side_effect=AssertionError(name))) "
            "for name in guards]; "
            "from modules.terminal.dispatch import TerminalToolDispatch; "
            "assert TerminalToolDispatch; stack.close()"
        )
        # Fixed interpreter and fixed program: no caller-controlled command or arguments.
        result = subprocess.run(  # noqa: S603
            [sys.executable, "-c", probe], capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
