from __future__ import annotations

import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from briareus_server.terminal.manager import TerminalError, TerminalManager
from briareus_server.terminal.settings import TerminalSettings
from briareus_terminal_policy import TerminalRuntimePolicy
from test_briareus_git_auth_guidance import discovery_for


class TerminalProcessContracts(unittest.IsolatedAsyncioTestCase):
    async def test_git_auth_failure_without_discovery_preserves_exec_and_job_results(self) -> None:
        command = "echo 'fatal: Authentication failed' >&2; exit 128"
        result = await self.manager.terminal_exec("fixture", command)
        self.assertEqual(result["exit_code"], 128)
        self.assertNotIn("git_auth_hint", result)
        job = await self.manager.job_start("fixture", command)
        await self.manager.job_wait(str(job["job_id"]), timeout_seconds=3)
        output = await self.manager.job_read(str(job["job_id"]))
        self.assertEqual(output["state"], "failed")
        self.assertNotIn("git_auth_hint", output)

    async def test_git_auth_failure_guides_exec_and_retained_job_to_mcp(self) -> None:
        self.manager.git_discovery = discovery_for("github", "gitlab")
        command = "echo 'fatal: Authentication failed' >&2; exit 128"
        result = await self.manager.terminal_exec("fixture", command)
        self.assertEqual(result["exit_code"], 128)
        self.assertIn("github_authorize_local_git", str(result["git_auth_hint"]))
        job = await self.manager.job_start("fixture", command)
        await self.manager.job_wait(str(job["job_id"]), timeout_seconds=3)
        output = await self.manager.job_read(str(job["job_id"]))
        self.assertIn("authorize_local_git", str(output["git_auth_hint"]))

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.manager = TerminalManager(TerminalSettings(workspace_root=root, home=root / "home"))
        self.manager.workspace_create("fixture")

    async def test_auto_retention_deletes_only_old_completed_jobs(self) -> None:
        completed = await self.manager.job_start("fixture", "echo complete")
        completed_id = str(completed["job_id"])
        await self.manager.job_wait(completed_id, timeout_seconds=3)
        old = self.manager._get_job(completed_id)
        old.ended_at = time.time() - 8 * 24 * 3600
        self.manager._persist(old)
        active = await self.manager.job_start("fixture", "sleep 30")
        active_id = str(active["job_id"])
        self.manager.settings = self.manager.settings.model_copy(
            update={"job_retention_hours": 24, "cleanup_batch_size": 10}
        )
        scanned = asyncio.Event()
        cleanup = self.manager.job_cleanup

        def recorded_cleanup(*, older_than_hours: int, dry_run: bool, limit: int) -> object:
            result = cleanup(
                older_than_hours=older_than_hours, dry_run=dry_run, limit=limit
            )
            scanned.set()
            return result

        with patch.object(self.manager, "job_cleanup", side_effect=recorded_cleanup):
            cleaner = asyncio.create_task(self.manager.auto_cleanup())
            try:
                await asyncio.wait_for(scanned.wait(), timeout=3)
                self.assertNotIn(completed_id, self.manager._jobs)
                self.assertIn(active_id, self.manager._jobs)
                self.assertEqual(self.manager._get_job(active_id).state, "running")
                self.assertTrue(self.manager.workspace_path("fixture").is_dir())
            finally:
                cleaner.cancel()
                await asyncio.gather(cleaner, return_exceptions=True)
                await self.manager.job_cancel(active_id)

    async def test_auto_retention_can_be_disabled(self) -> None:
        self.manager.settings = self.manager.settings.model_copy(
            update={"auto_cleanup_enabled": False}
        )
        await asyncio.wait_for(self.manager.auto_cleanup(), timeout=1)

    async def test_exited_shell_cannot_retain_a_job_slot_through_inherited_stdout(self) -> None:
        job = await self.manager.job_start("fixture", "sleep 30 & echo finished")
        result = await self.manager.job_wait(str(job["job_id"]), timeout_seconds=3)
        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["exit_code"], 0)
        self.assertIsNone(result["pid"])

    async def test_exec_drains_output_and_terminates_children_after_shell_exit(self) -> None:
        async with asyncio.timeout(4):
            result = await self.manager.terminal_exec("fixture", "sleep 30 & echo finished")
        self.assertFalse(result["timed_out"])
        self.assertEqual(result["stdout"], "finished\n")

    async def test_commands_and_jobs_share_one_limit_and_release_after_cancellation(self) -> None:
        policy = TerminalRuntimePolicy(max_concurrent_processes=1)
        with patch.object(self.manager, "_runtime_policy", return_value=policy):
            job = await self.manager.job_start("fixture", "sleep 30")
            with self.assertRaisesRegex(TerminalError, "process limit"):
                await self.manager.terminal_exec("fixture", "echo rejected")
            with self.assertRaisesRegex(TerminalError, "process limit"):
                await self.manager.job_start("fixture", "echo rejected")
            await self.manager.job_cancel(str(job["job_id"]))
            result = await self.manager.terminal_exec("fixture", "echo admitted")
            self.assertEqual(result["stdout"], "admitted\n")

    async def test_concurrent_exec_admission_is_atomic(self) -> None:
        policy = TerminalRuntimePolicy(max_concurrent_processes=1)
        with patch.object(self.manager, "_runtime_policy", return_value=policy):
            first = asyncio.create_task(self.manager.terminal_exec("fixture", "sleep 0.3"))
            await asyncio.sleep(0)
            try:
                with self.assertRaisesRegex(TerminalError, "process limit"):
                    await self.manager.job_start("fixture", "echo rejected")
            finally:
                await first
