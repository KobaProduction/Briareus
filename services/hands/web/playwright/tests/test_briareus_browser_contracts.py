from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock, patch
from xmlrpc.client import dumps

import httpx
from briareus_json_values import json_object_list
from briareus_playwright.browser import BrowserError, BrowserManager
from briareus_playwright.browser_control import BrowserControlClient, BrowserControlState
from briareus_playwright.browser_extensions import BrowserExtensionRegistry
from briareus_playwright.browser_launch import BrowserLaunchSource
from briareus_playwright.browser_profile import BrowserDesktopProfile
from briareus_playwright.settings import BrowserSettings
from briareus_workspace.workspace_store import WorkspaceFileStore

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page, Playwright


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


class DisconnectedContext:
    def __init__(self) -> None:
        self.pages: list[Page] = []

    def set_default_timeout(self, timeout: float) -> None:
        del timeout

    def set_default_navigation_timeout(self, timeout: float) -> None:
        del timeout

    def on(self, event: str, callback: Callable[[Page], None]) -> None:
        del event, callback

    async def new_page(self) -> None:
        raise BrowserError("Remote browser transport disconnected")


class ExternalChromiumConnection:
    def __init__(self) -> None:
        self.contexts = [DisconnectedContext()]
        self.attachments: list[str] = []

    def is_connected(self) -> bool:
        return False

    async def connect_over_cdp(self, endpoint: str, **options: float) -> ExternalChromiumConnection:
        del options
        self.attachments.append(endpoint)
        return self


class ExternalDriver:
    def __init__(self, connection: ExternalChromiumConnection) -> None:
        self.chromium = connection

    async def start(self) -> ExternalDriver:
        return self


class BrowserLifecycleContracts(unittest.IsolatedAsyncioTestCase):
    async def test_unattached_status_uses_external_owner_and_reports_disconnected_context(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(Path(directory))
            remote = ExternalChromiumConnection()
            requests: list[tuple[str, str]] = []

            def respond(request: httpx.Request) -> httpx.Response:
                requests.append((request.method, request.url.path))
                if request.url.path == "/RPC2":
                    return httpx.Response(200, content=dumps(({"state": 20},), methodresponse=True))
                self.assertEqual(request.url.path, "/json/version")
                return httpx.Response(200, json={"Browser": "Chromium"})

            client_type = httpx.AsyncClient

            def http_client(*, timeout: float) -> httpx.AsyncClient:
                return client_type(transport=httpx.MockTransport(respond), timeout=timeout)

            self.assertIsNone(manager._context)
            with (
                patch("playwright.async_api.async_playwright", return_value=ExternalDriver(remote)),
                patch("httpx.AsyncClient", side_effect=http_client),
            ):
                status = await manager.status()
            self.assertEqual(remote.attachments, [manager.cdp_url])
            self.assertTrue(status["process_running"])
            self.assertTrue(status["cdp_reachable"])
            self.assertFalse(status["context_usable"])
            self.assertFalse(status["running"])
            self.assertFalse(status["manually_stopped"])
            self.assertEqual(status["pages"], [])
            self.assertEqual(requests, [("POST", "/RPC2")] * 2 + [("GET", "/json/version")])

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
            control_url="http://chromium:9001/RPC2",
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
            source = BrowserLaunchSource(settings, desktop, workspace)
            with patch.dict("os.environ", {"FILE_WORKSPACE_ROOT": str(workspace)}):
                self.assertEqual(source.current().extension_paths, ())
                registry.record("extension-A", str(extension))
                current = source.current()
                command = current.arguments()
                manifest = source.write_manifest()
                self.assertEqual(json.loads(manifest.read_text()), list(command))
                registry.remove("extension-A")
                self.assertEqual(source.current().extension_paths, ())
            self.assertIn("--load-extension=" + str(extension), command)
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


class BrowserPageSummaryContracts(unittest.IsolatedAsyncioTestCase):
    async def test_title_deadlines_do_not_accumulate_across_many_blocked_tabs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = BrowserLifecycleContracts.manager(Path(directory))
            manager._control = cast(BrowserControlClient, ProcessControl())
            context = MagicMock()
            context.pages = []
            for index in range(8):
                page = MagicMock()
                page.url = f"https://blocked-{index}.example"
                page.is_closed.return_value = False
                page.title = AsyncMock(side_effect=asyncio.Event().wait)
                context.pages.append(page)
            manager._context = cast("BrowserContext", context)
            with (
                patch("briareus_playwright.browser._PAGE_TITLE_TIMEOUT_SECONDS", 0.05),
                patch.object(manager, "_cdp_reachable", new_callable=AsyncMock, return_value=True),
                patch.object(manager, "_context_usable", new_callable=AsyncMock, return_value=True),
                patch.object(manager, "_observed_runtime", new_callable=AsyncMock, return_value={}),
            ):
                async with asyncio.timeout(0.25):
                    result = await manager.pages()
            self.assertEqual(result["count"], 8)
            self.assertTrue(all(page["title"] == "" for page in json_object_list(result["pages"])))

    async def test_a_wedged_title_does_not_block_listing_healthy_tabs_or_restart_chromium(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = BrowserLifecycleContracts.manager(Path(directory))
            control = ProcessControl()
            manager._control = cast(BrowserControlClient, control)
            wedged = MagicMock()
            wedged.url = "https://failed-navigation.example"
            wedged.is_closed.return_value = False
            wedged.title = AsyncMock(side_effect=asyncio.Event().wait)
            healthy = MagicMock()
            healthy.url = "https://healthy.example"
            healthy.is_closed.return_value = False
            healthy.title = AsyncMock(return_value="Healthy tab")
            context = MagicMock()
            context.pages = [wedged, healthy]
            manager._context = cast("BrowserContext", context)
            with (
                patch("briareus_playwright.browser._PAGE_TITLE_TIMEOUT_SECONDS", 0.01),
                patch.object(manager, "_cdp_reachable", new_callable=AsyncMock, return_value=True),
                patch.object(manager, "_context_usable", new_callable=AsyncMock, return_value=True),
                patch.object(manager, "_observed_runtime", new_callable=AsyncMock, return_value={}),
            ):
                async with asyncio.timeout(0.5):
                    result = await manager.pages()
            pages = json_object_list(result["pages"])
            self.assertEqual(result["count"], 2)
            self.assertEqual([page["title"] for page in pages], ["", "Healthy tab"])
            self.assertEqual(pages[0]["url"], wedged.url)
            self.assertEqual(control.commands, ["state"])

    async def test_cancelled_summary_propagates_cancellation(self) -> None:
        started = asyncio.Event()

        async def blocked_title() -> str:
            started.set()
            await asyncio.Event().wait()
            return "unreachable"

        page = MagicMock()
        page.title = AsyncMock(side_effect=blocked_title)
        pending = asyncio.create_task(BrowserManager._page_title(cast("Page", page)))
        await started.wait()
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await pending

