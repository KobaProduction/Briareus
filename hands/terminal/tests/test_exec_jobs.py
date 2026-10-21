"""Command lifetime is independent of a bounded initial observation."""
import asyncio
import json
import tempfile
import time
import unittest
from unittest.mock import patch

from common.settings import TerminalSettings
from modules.terminal.manager import TerminalManager
from node_protocol.terminal import parse_request


class ExecJobTests(unittest.IsolatedAsyncioTestCase):
    async def test_long_exec_is_retained_without_default_execution_timeout(self):
        with tempfile.TemporaryDirectory() as root, patch.dict("os.environ", {"BRIAREUS_RUNTIME_POLICY":"{}"}):
            manager=TerminalManager(TerminalSettings(TERMINAL_WORKSPACE_ROOT=root+"/work",TERMINAL_HOME=root+"/home"))
            manager.workspace_create("fixture")
            try:
                with patch.object(manager,"_require_offline_executor"):
                    began=time.monotonic()
                    result=await manager.terminal_exec("fixture","sleep 4; printf retained-ok")
                self.assertLess(time.monotonic()-began,3)
                self.assertEqual(result["state"],"running")
                self.assertIsNone(result["timeout_seconds"])
                await manager.job_wait(result["job_id"],timeout_seconds=5)
                output=await manager.job_read(result["job_id"],cursor=result["next_cursor"])
                self.assertIn("retained-ok",output["output"])
                self.assertEqual(output["state"],"completed")
            finally:
                for job in manager._jobs.values():
                    if job.state in {"running","cancelling"}:await manager.job_cancel(job.job_id,grace_seconds=.1)

    async def test_configured_execution_timeout_still_terminates_command(self):
        with tempfile.TemporaryDirectory() as root, patch.dict("os.environ", {"BRIAREUS_RUNTIME_POLICY":'{"execution_timeout_seconds":0.1}'}):
            manager=TerminalManager(TerminalSettings(TERMINAL_WORKSPACE_ROOT=root+"/work",TERMINAL_HOME=root+"/home"))
            manager.workspace_create("fixture")
            try:
                with patch.object(manager,"_require_offline_executor"):
                    result=await manager.terminal_exec("fixture","sleep 10")
                self.assertEqual(result["timeout_seconds"],.1)
                state=await manager.job_wait(result["job_id"],timeout_seconds=4)
                self.assertEqual(state["state"],"timed_out")
            finally:
                for job in manager._jobs.values():
                    if job.state in {"running","cancelling"}:await manager.job_cancel(job.job_id,grace_seconds=.1)

    def test_execution_timeout_has_no_hidden_three_second_wire_limit(self):
        for timeout in (None,600):
            wire=json.dumps({"jsonrpc":"2.0","method":"tools/call","params":{
                "name":"terminal_exec","arguments":{"workspace_id":"fixture","command":"fixture","timeout_seconds":timeout}}}).encode()
            self.assertEqual(parse_request(wire).arguments["timeout_seconds"],timeout)
