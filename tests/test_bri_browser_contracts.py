from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import patch

from browser_runtime.application import BrowserLifecycle, BrowserProcessState
from browser_runtime.configuration import BrowserLaunchSource
from browser_runtime.process import ChromiumProcess
from common.browser_extensions import BrowserExtensionRegistry
from common.browser_profile import BrowserDesktopProfile
from common.settings import BrowserSettings
from modules.files.workspace_store import WorkspaceFileStore
from modules.web.browser import BrowserError, BrowserManager
from modules.web.browser_control import BrowserControlClient, BrowserControlState

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Playwright


class OwnedProcess:
    def __init__(self) -> None:
        self.events: list[tuple[str, bool]] = []
        self.running = False
        self.stopped = False

    def state(self) -> BrowserProcessState:
        return BrowserProcessState(self.running, 123 if self.running else None, self.stopped)

    async def start(self) -> None:
        self.events.append(("start", False))
        self.running, self.stopped = True, False

    async def stop(self, *, force: bool = False) -> None:
        self.events.append(("stop", force))
        self.running, self.stopped = False, True


class BrowserConnection:
    def __init__(self) -> None:
        self.close_calls = 0

    async def close(self) -> None:
        self.close_calls += 1


class DriverConnection:
    def __init__(self) -> None:
        self.stops = 0

    async def stop(self) -> None:
        self.stops += 1


class ProcessControl:
    def __init__(self) -> None:
        self.commands: list[str] = []

    async def command(self, action: str) -> BrowserControlState:
        self.commands.append(action)
        return BrowserControlState(action != "stop", action == "stop")


class BrowserLifecycleContracts(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_restart_and_hard_stop_have_distinct_process_semantics(self) -> None:
        process = OwnedProcess()
        lifecycle = BrowserLifecycle(process)
        self.assertTrue((await lifecycle.execute("start")).running)
        self.assertTrue((await lifecycle.execute("restart")).running)
        stopped = await lifecycle.execute("stop")
        self.assertFalse(stopped.running)
        self.assertTrue(stopped.manually_stopped)
        self.assertEqual(
            process.events,
            [
                ("start", False),
                ("stop", False),
                ("start", False),
                ("stop", True),
            ],
        )

    async def test_web_detach_disconnects_only_its_driver_and_preserves_remote_browser(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = self.manager(root)
            driver, browser, context, control = (
                DriverConnection(),
                BrowserConnection(),
                BrowserConnection(),
                ProcessControl(),
            )
            manager._playwright = cast("Playwright", driver)
            manager._browser = cast("Browser", browser)
            manager._context = cast("BrowserContext", context)
            manager._control = cast(BrowserControlClient, control)
            await manager._stop_runtime(stop_display=False)
            self.assertEqual(driver.stops, 1)
            self.assertEqual(browser.close_calls, 0)
            self.assertEqual(context.close_calls, 0)
            self.assertEqual(control.commands, [])

    async def test_explicit_stop_preserves_profile_and_requires_an_explicit_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = self.manager(root)
            control = ProcessControl()
            manager._control = cast(BrowserControlClient, control)
            marker = manager.profile_dir / "profile-marker"
            marker.parent.mkdir(parents=True)
            marker.write_text("keep")
            result = await manager.hard_stop()
            self.assertTrue(result["profile_preserved"])
            self.assertEqual(control.commands, ["stop"])
            self.assertEqual(marker.read_text(), "keep")
            with self.assertRaises(BrowserError):
                await manager._ensure_started()

    @staticmethod
    def manager(root: Path) -> BrowserManager:
        return BrowserManager(
            workspace=WorkspaceFileStore(root / "workspace"),
            cdp_url="http://chromium:9222",
            control_url="http://chromium:9222/control",
            control_token="test-browser-control",
            profile_dir=root / "browser/profile",
            executable_path="/usr/bin/chromium",
            headless=True,
            timeout_ms=1000,
            viewport_width=1200,
            viewport_height=800,
            max_snapshot_text_chars=1000,
            max_snapshot_elements=50,
        )


class BrowserLaunchPersistenceContracts(unittest.TestCase):
    def test_restart_reads_current_extension_registry_and_existing_profile_policy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace, profile = root / "workspace", root / "browser/profile"
            extension = workspace / "extensions/example"
            extension.mkdir(parents=True)
            profile.mkdir(parents=True)
            (profile / "koba-browser-policy.json").write_text(json.dumps({"color_scheme": "light"}))
            registry = BrowserExtensionRegistry(profile.parent / "dev-extensions.json", workspace)
            settings = BrowserSettings(
                profile_dir=profile, executable_path="/custom/chromium", timezone="Europe/Moscow"
            )
            desktop = BrowserDesktopProfile(
                headless=True,
                locale="fr-FR",
                viewport_width=1400,
                viewport_height=900,
                chromium_args=("--force-device-scale-factor=1.25",),
            )
            source = BrowserLaunchSource(settings, desktop)
            with patch.dict("os.environ", {"FILE_WORKSPACE_ROOT": str(workspace)}):
                self.assertEqual(source.current().extension_paths, ())
                registry.record("extension-A", str(extension))
                current = source.current()
                process = ChromiumProcess(source)
                command = process.command(current)
                registry.remove("extension-A")
                self.assertEqual(source.current().extension_paths, ())
            self.assertIn("--load-extension=" + str(extension), command)
            self.assertIn("--user-data-dir=" + str(profile), command)
            self.assertIn("--window-size=1400,900", command)
            self.assertIn("--lang=fr-FR", command)
            self.assertIn("--force-device-scale-factor=1.25", command)
            self.assertNotIn("--force-dark-mode", command)
            self.assertEqual(current.timezone, "Europe/Moscow")

    def test_extension_registry_rejects_cross_workspace_paths_and_persists_removal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            extension = workspace / "extension"
            extension.mkdir(parents=True)
            path = root / "browser/dev-extensions.json"
            registry = BrowserExtensionRegistry(path, workspace)
            with self.assertRaises(ValueError):
                registry.record("escape", str(root / "private"))
            registry.record("valid", str(extension))
            self.assertEqual(
                BrowserExtensionRegistry(path, workspace).load_paths(), (str(extension),)
            )
            registry.remove("valid")
            self.assertEqual(BrowserExtensionRegistry(path, workspace).load_paths(), ())
