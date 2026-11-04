from __future__ import annotations

import json
import unittest

from briareus_hand_runtime.tool_observability import (
    invocation_arguments_payload,
    invocation_result_payload,
)


class ServerAuditContracts(unittest.TestCase):
    def test_terminal_commands_are_bounded_and_stdin_is_omitted_under_server_scope(self) -> None:
        command = "x" * 3000
        payload = json.loads(
            invocation_arguments_payload(
                "server", {"command": command, "data": "private-stdin"}, "terminal_exec"
            )
        )
        self.assertTrue(payload["command"].startswith("x" * 2048))
        self.assertIn("<truncated", payload["command"])
        self.assertLess(len(payload["command"]), 2200)
        self.assertEqual(payload["data"], "<omitted 13 chars>")
        self.assertNotIn("private-stdin", str(payload))

    def test_job_stdin_and_terminal_results_remain_private_after_runtime_merge(self) -> None:
        arguments = invocation_arguments_payload(
            "server", {"job_id": "fixture-job", "data": "private-job-input"}, "job_write"
        )
        self.assertNotIn("private-job-input", arguments)
        self.assertEqual(json.loads(arguments)["job_id"], "fixture-job")
        for tool in ("terminal_exec", "job_read", "workspace_list"):
            with self.subTest(tool=tool):
                result = invocation_result_payload("server", {"stdout": "private-output"}, tool)
                self.assertNotIn("private-output", result)
                self.assertIn("omitted", result)

    def test_file_metadata_keeps_its_own_audit_behavior(self) -> None:
        arguments = {"path": "projects/example/file.txt", "offset": 0}
        result = {"path": "projects/example/file.txt", "size_bytes": 42}
        self.assertEqual(
            json.loads(invocation_arguments_payload("server", arguments, "file_info")), arguments
        )
        self.assertEqual(
            json.loads(invocation_result_payload("server", result, "file_info")), result
        )
