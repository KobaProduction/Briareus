"""IPC reuses original callable signatures without starting another MCP SDK."""
import subprocess
import sys
import unittest

from pydantic import ValidationError

from modules.terminal.dispatch import TerminalToolDispatch
from node_protocol.terminal import TOOLS


class RecordingManager:
    def __init__(self):
        self.commands = []

    def status(self):
        return {"uid": 1000}

    async def terminal_exec(self, workspace, command, **options):
        self.commands.append((workspace, command, options))
        return {"exit_code": 0, "stdout": "ok"}

    async def job_cancel(self, job_id, *, grace_seconds):
        self.commands.append((job_id, grace_seconds))
        return {"state": "cancelled"}


class ToolDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_bounds_are_validated_before_manager_and_exposed_to_agents(self):
        from fastmcp import FastMCP
        from modules.terminal.tools import register_terminal_tools

        manager = RecordingManager()
        dispatch = TerminalToolDispatch(manager)
        for invalid in (0, -1, 3.1, False, float("nan"), float("inf")):
            with self.assertRaises(ValidationError):
                await dispatch.call("job_cancel", {"job_id": "owned", "grace_seconds": invalid})
        self.assertEqual(manager.commands, [])
        await dispatch.call("job_cancel", {"job_id": "owned", "grace_seconds": 0.5})
        self.assertEqual(manager.commands, [("owned", 0.5)])
        mcp = FastMCP("schema")
        register_terminal_tools(mcp, manager)
        tool = await mcp.get_tool("job_cancel")
        parameter = tool.parameters["properties"]["grace_seconds"]
        self.assertEqual(parameter["exclusiveMinimum"], 0)
        self.assertEqual(parameter["maximum"], 3)

    async def test_known_tools_typed_defaults_and_no_unvalidated_command(self):
        manager = RecordingManager()
        dispatch = TerminalToolDispatch(manager)
        self.assertEqual(set(dispatch.tools), TOOLS)
        result = await dispatch.call("terminal_exec", {
            "workspace_id": "team", "command": "printf ok"})
        self.assertEqual(result, {"exit_code": 0, "stdout": "ok"})
        self.assertEqual(manager.commands[0][0:2], ("team", "printf ok"))
        self.assertEqual(manager.commands[0][2]["cwd"], "")
        self.assertIsNone(manager.commands[0][2]["env"])
        self.assertEqual(manager.commands[0][2]["timeout_seconds"],3)
        for invalid in [
            {"workspace_id": "team", "command": ["bad"]},
            {"workspace_id": "team", "command": "bad", "escape": True},
            {"workspace_id": "team", "command": "bad", "timeout_seconds": "3"},
        ]:
            with self.assertRaises(ValidationError):
                await dispatch.call("terminal_exec", invalid)
        with self.assertRaises(KeyError):
            await dispatch.call("__getattribute__", {"name": "settings"})
        self.assertEqual(len(manager.commands), 1)

    def test_child_dispatch_import_has_no_mcp_sdk(self):
        result = subprocess.run([sys.executable, "-c",
            "import sys; from modules.terminal.dispatch import TerminalToolDispatch; "
            "assert not any(k == 'fastmcp' or k.startswith('fastmcp.') or "
            "k == 'mcp' or k.startswith('mcp.') for k in sys.modules)"],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
