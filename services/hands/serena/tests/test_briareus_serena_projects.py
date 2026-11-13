from __future__ import annotations

import asyncio
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from briareus_mcp_client.mcp_client_pool import SessionClient
from briareus_serena.models import ProjectSpec, SerenaSettings
from briareus_serena.projects import ProjectManager
from fastmcp import Client, FastMCP


class SerenaProjectContracts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        for name in ("alpha", "beta"):
            folder = self.workspace / name
            folder.mkdir()
            (folder / "marker.txt").write_text(name)
        self.settings = SerenaSettings(
            workspace_root=self.workspace, state_root=self.root / "state", max_processes=2
        )
        self.manager = ProjectManager(self.settings, factory=self.engine)
        self.addAsyncCleanup(self.manager.close)
        for name in ("alpha", "beta"):
            await self.manager.register(ProjectSpec(project_id=name, folder=name))

    def engine(self, project: ProjectSpec) -> SessionClient:
        server = FastMCP(project.project_id)

        @server.tool
        async def marker() -> str:
            return (Path(project.folder) / "marker.txt").read_text()

        @server.tool
        async def wait_for_release() -> str:
            self.started.set()
            await self.release.wait()
            return project.project_id

        return Client(server)

    def test_bounded_default_configuration_can_be_overridden(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = SerenaSettings()
        self.assertEqual(settings.max_processes, 2)
        self.assertEqual(settings.idle_seconds, 300)
        self.assertEqual(settings.reap_interval_seconds, 15)
        tuned = SerenaSettings(
            max_processes=3, idle_seconds=60, reap_interval_seconds=5
        )
        self.assertEqual((tuned.max_processes, tuned.idle_seconds, tuned.reap_interval_seconds),
                         (3, 60, 5))

    async def test_failed_idle_close_does_not_block_another_project(self) -> None:
        await self.manager.call_tool("marker", {"project_id": "alpha"})
        await self.manager.call_tool("marker", {"project_id": "beta"})
        for process in self.manager.processes.values():
            process.last_used = time.monotonic() - 1000
        close = self.manager._close

        async def fail_alpha(project_id: str) -> None:
            if project_id == "alpha":
                raise RuntimeError("simulated child shutdown failure")
            await close(project_id)

        with patch.object(self.manager, "_close", side_effect=fail_alpha):
            await self.manager.reap_idle_projects()
        self.assertEqual(set(self.manager.processes), {"alpha"})
        await self.manager.reap_idle_projects()
        self.assertFalse(self.manager.processes)

    async def test_simultaneous_projects_keep_their_own_server_folder_and_session(self) -> None:
        alpha, beta = await asyncio.gather(
            self.manager.call_tool("marker", {"project_id": "alpha"}),
            self.manager.call_tool("marker", {"project_id": "beta"}),
        )
        self.assertEqual((alpha.data, beta.data), ("alpha", "beta"))
        self.assertEqual(set(self.manager.processes), {"alpha", "beta"})
        self.assertEqual(
            (await self.manager.call_tool("marker", {"project_id": "alpha"})).data, "alpha"
        )

    async def test_registration_survives_restart_without_restarting_children(self) -> None:
        restored = ProjectManager(self.settings, factory=self.engine)
        self.addAsyncCleanup(restored.close)
        self.assertEqual(set(restored.projects), {"alpha", "beta"})
        self.assertTrue(
            all(restored.status(p).state == "stopped" for p in restored.projects.values())
        )
        self.assertEqual((await restored.call_tool("marker", {"project_id": "beta"})).data, "beta")

    async def test_moved_server_folder_does_not_block_other_project_registration(self) -> None:
        (self.workspace / "beta").rename(self.workspace / "moved-beta")
        registered = await self.manager.register(
            ProjectSpec(project_id="moved-beta", folder="moved-beta")
        )
        self.assertEqual(registered.state, "stopped")
        self.assertEqual(
            (await self.manager.call_tool("marker", {"project_id": "moved-beta"})).data, "beta"
        )
        with self.assertRaises(ValueError):
            await self.manager.call_tool("marker", {"project_id": "beta"})

    async def test_outside_folders_symlinks_and_duplicate_folder_aliases_are_rejected(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        for folder in (str(outside), "../outside"):
            with self.subTest(folder=folder), self.assertRaises(ValueError):
                await self.manager.register(ProjectSpec(project_id="escape", folder=folder))
        with self.assertRaises(ValueError):
            await self.manager.register(ProjectSpec(project_id="alias", folder="alpha"))
        link = self.workspace / "escape"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            return
        with self.assertRaises(ValueError):
            await self.manager.register(ProjectSpec(project_id="escape", folder="escape"))

    async def test_process_limit_evicts_only_idle_project_and_keeps_files(self) -> None:
        self.manager.settings = self.settings.model_copy(update={"max_processes": 1})
        await self.manager.call_tool("marker", {"project_id": "alpha"})
        await self.manager.call_tool("marker", {"project_id": "beta"})
        self.assertEqual(set(self.manager.processes), {"beta"})
        self.assertTrue((self.workspace / "alpha/marker.txt").exists())
        self.manager.processes["beta"].last_used = time.monotonic() - 1000
        await self.manager.reap_idle_projects()
        self.assertFalse(self.manager.processes)
        await self.manager.unregister("beta")
        self.assertTrue((self.workspace / "beta/marker.txt").exists())

    async def test_active_project_is_not_stopped_or_rebound_and_shutdown_releases_it(self) -> None:
        self.manager.settings = self.settings.model_copy(update={"max_processes": 1})
        pending = asyncio.create_task(
            self.manager.call_tool("wait_for_release", {"project_id": "alpha"})
        )
        await asyncio.wait_for(self.started.wait(), timeout=10)
        with self.assertRaises(ValueError):
            await self.manager.close_project("alpha")
        with self.assertRaises(ValueError):
            await self.manager.call_tool("marker", {"project_id": "beta"})
        with self.assertRaises(ValueError):
            await self.manager.register(ProjectSpec(project_id="alpha", folder="beta"))
        await self.manager.close()
        with self.assertRaises(asyncio.CancelledError):
            await pending
        self.assertFalse(self.manager.processes)
