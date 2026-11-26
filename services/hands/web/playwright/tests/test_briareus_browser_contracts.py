from __future__ import annotations

import asyncio
import json
import logging
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock, patch
from xmlrpc.client import dumps

import httpx
from briareus_json_values import json_object_list
from briareus_playwright.browser import (
    BrowserError,
    BrowserManager,
    BrowserRequestError,
    BrowserStaleStateError,
)
from briareus_playwright.browser_control import BrowserControlClient, BrowserControlState
from briareus_playwright.browser_extensions import BrowserExtensionRegistry
from briareus_playwright.browser_launch import BrowserLaunchSource
from briareus_playwright.browser_profile import BrowserDesktopProfile
from briareus_playwright.settings import BrowserSettings
from briareus_workspace.workspace_store import WorkspaceFileStore
from fastmcp.exceptions import ToolError
from playwright._impl._transport import PipeTransport
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright
from playwright.async_api._context_manager import PlaywrightContextManager
from pydantic import ValidationError

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
        self.connection_options: list[dict[str, float]] = []

    def is_connected(self) -> bool:
        return False

    async def connect_over_cdp(self, endpoint: str, **options: float) -> ExternalChromiumConnection:
        self.connection_options.append(options)
        self.attachments.append(endpoint)
        return self


class ExternalDriver:
    def __init__(self, connection: ExternalChromiumConnection) -> None:
        self.chromium = connection
        self.stop = AsyncMock()

    async def start(self) -> ExternalDriver:
        return self


class BrowserLifecycleContracts(unittest.IsolatedAsyncioTestCase):
    def test_connection_and_idle_retry_deadlines_are_configurable(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "BROWSER_CLICK_TIMEOUT_MS": "3500",
                "BROWSER_CDP_CONNECT_TIMEOUT_MS": "5000",
                "BROWSER_IDLE_RECONNECT_BACKOFF_SECONDS": "75",
                "BROWSER_IDLE_CLEANUP_INTERVAL_SECONDS": "15",
                "BROWSER_DEVELOPER_SYNC_TIMEOUT_MS": "4200",
                "BROWSER_STARTUP_TIMEOUT_MS": "48000",
            },
        ):
            settings = BrowserSettings()
        self.assertEqual(settings.cdp_connect_timeout_ms, 5000)
        self.assertEqual(settings.developer_sync_timeout_ms, 4200)
        self.assertEqual(settings.startup_timeout_ms, 48000)
        self.assertEqual(settings.click_timeout_ms, 3500)
        self.assertEqual(settings.idle_reconnect_backoff_seconds, 75.0)
        self.assertEqual(settings.idle_cleanup_interval_seconds, 15.0)
        with self.assertRaises(ValidationError):
            BrowserSettings(click_timeout_ms=500)
        with self.assertRaises(ValidationError):
            BrowserSettings(cdp_connect_timeout_ms=500)
        with self.assertRaises(ValidationError):
            BrowserSettings(developer_sync_timeout_ms=500)
        with self.assertRaises(ValidationError):
            BrowserSettings(startup_timeout_ms=500)
        with self.assertRaises(ValidationError):
            BrowserSettings(idle_reconnect_backoff_seconds=0)

    async def test_hanging_extension_sync_does_not_block_cdp_startup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(Path(directory))
            manager.developer_sync_timeout_ms = 25
            manager._control = cast(BrowserControlClient, ProcessControl())
            remote = ExternalChromiumConnection()

            async def stalled_sync(*_args: object, **_kwargs: object) -> None:
                await asyncio.Event().wait()

            with (
                patch("playwright.async_api.async_playwright", return_value=ExternalDriver(remote)),
                patch.object(manager, "_set_chromium_developer_state", side_effect=stalled_sync),
            ):
                await asyncio.wait_for(manager._start_locked(), timeout=0.5)
            self.assertIs(manager._context, remote.contexts[0])
            self.assertIn("timed out", manager._user_scripts_sync_error)
            await manager._stop_runtime(stop_display=False)

    async def test_stalled_tab_registration_fails_startup_and_discards_partial_session(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(Path(directory))
            manager.startup_timeout_ms = 25
            manager._control = cast(BrowserControlClient, ProcessControl())
            remote = ExternalChromiumConnection()
            remote.contexts[0].pages = [cast("Page", MagicMock())]
            driver = ExternalDriver(remote)
            driver.stop = AsyncMock()

            async def stalled_registration(_page: Page) -> str:
                await asyncio.Event().wait()
                return "unreachable"

            with (
                patch("playwright.async_api.async_playwright", return_value=driver),
                patch.object(manager, "_register_page", side_effect=stalled_registration),
                patch.object(manager, "_set_chromium_developer_state", new_callable=AsyncMock),
                self.assertRaisesRegex(BrowserError, "startup exceeded 25 ms"),
            ):
                await asyncio.wait_for(manager._ensure_started(), timeout=0.5)
            self.assertFalse(manager._start_lock.locked())
            self.assertIsNone(manager._context)
            self.assertIsNone(manager._browser)
            self.assertIsNone(manager._playwright)
            driver.stop.assert_awaited_once()

    async def test_stalled_cdp_startup_clears_partial_state_and_allows_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(Path(directory))
            manager.startup_timeout_ms = 20
            manager._control = cast(BrowserControlClient, ProcessControl())
            driver = DriverConnection()

            async def stalled_start() -> None:
                manager._playwright = cast("Playwright", driver)
                manager._context = cast("BrowserContext", DisconnectedContext())
                await asyncio.Event().wait()

            with (
                patch.object(manager, "_start_locked", side_effect=stalled_start),
                self.assertRaisesRegex(BrowserError, "startup exceeded 20 ms"),
            ):
                await asyncio.wait_for(manager._ensure_started(), timeout=0.5)
            self.assertFalse(manager._start_lock.locked())
            self.assertIsNone(manager._context)
            self.assertIsNone(manager._playwright)
            self.assertEqual(driver.stops, 1)
            with self.assertRaisesRegex(BrowserError, "reconnect cooldown"):
                await manager._ensure_started()
            manager._next_idle_reconnect_at = 0.0
            recovered = DisconnectedContext()

            async def recovered_start() -> None:
                manager._context = cast("BrowserContext", recovered)

            with (
                patch.object(manager, "_start_locked", side_effect=recovered_start),
                patch.object(
                    manager, "_context_usable", new_callable=AsyncMock, return_value=False
                ),
            ):
                self.assertIs(await manager._ensure_started(), recovered)

    async def test_failed_startup_on_non_timeout_error_discards_partial_connection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(Path(directory))
            manager._control = cast(BrowserControlClient, ProcessControl())
            driver = DriverConnection()

            async def broken_start() -> None:
                manager._playwright = cast("Playwright", driver)
                manager._context = cast("BrowserContext", DisconnectedContext())
                raise BrowserError("CDP target lost")

            with (
                patch.object(manager, "_start_locked", side_effect=broken_start),
                self.assertRaisesRegex(BrowserError, "CDP target lost"),
            ):
                await manager._ensure_started()
            self.assertIsNone(manager._context)
            self.assertIsNone(manager._playwright)
            self.assertEqual(driver.stops, 1)

    async def test_cancellation_of_disconnect_does_not_leave_partial_browser_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(Path(directory))
            manager._playwright = cast("Playwright", DriverConnection())
            manager._context = cast("BrowserContext", DisconnectedContext())
            manager._downloads.disconnect = AsyncMock(side_effect=asyncio.Event().wait)
            with self.assertRaises(TimeoutError):
                await asyncio.wait_for(manager._stop_runtime(stop_display=False), timeout=0.02)
            self.assertIsNone(manager._context)
            self.assertIsNone(manager._playwright)

    async def test_concurrent_cancelled_waiters_share_one_driver_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(Path(directory))
            manager._control = cast(BrowserControlClient, ProcessControl())
            remote = ExternalChromiumConnection()
            driver = ExternalDriver(remote)
            entered = asyncio.Event()
            release = asyncio.Event()

            async def stalled_attach(*_args: object, **_kwargs: object) -> None:
                entered.set()
                await release.wait()
                raise PlaywrightTimeoutError("CDP not responding")

            with (
                patch("playwright.async_api.async_playwright", return_value=driver) as factory,
                patch.object(remote, "connect_over_cdp", side_effect=stalled_attach),
            ):
                waiters = [asyncio.create_task(manager._ensure_started()) for _ in range(12)]
                await asyncio.wait_for(entered.wait(), timeout=1)
                for waiter in waiters[:-1]:
                    waiter.cancel()
                await asyncio.gather(*waiters[:-1], return_exceptions=True)
                factory.assert_called_once()
                driver.stop.assert_not_awaited()
                release.set()
                with self.assertRaises(PlaywrightTimeoutError):
                    await waiters[-1]
                driver.stop.assert_awaited_once()
                for _ in range(12):
                    with self.assertRaisesRegex(BrowserError, "reconnect cooldown"):
                        await manager._ensure_started()
                factory.assert_called_once()
                self.assertIsNone(manager._playwright)
                self.assertIsNone(manager._driver_stop_task)

    async def test_cancelled_driver_initialization_remains_owned_until_stopped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(Path(directory))
            manager._control = cast(BrowserControlClient, ProcessControl())
            manager.startup_timeout_ms = 20
            driver = ExternalDriver(ExternalChromiumConnection())
            entered = asyncio.Event()
            release = asyncio.Event()

            async def stalled_driver_start() -> ExternalDriver:
                entered.set()
                await release.wait()
                return driver

            with patch(
                "playwright.async_api.async_playwright", return_value=driver
            ) as factory, patch.object(driver, "start", side_effect=stalled_driver_start):
                recovery = asyncio.create_task(manager._ensure_started())
                await asyncio.wait_for(entered.wait(), timeout=1)
                await asyncio.sleep(0.05)
                self.assertFalse(recovery.done())
                release.set()
                with self.assertRaisesRegex(BrowserError, "startup exceeded"):
                    await recovery
                driver.stop.assert_awaited_once()
                self.assertIsNone(manager._driver_start_task)
                self.assertIsNone(manager._driver_stop_task)
                factory.assert_called_once()

    async def test_cancelled_cleanup_never_drops_live_driver(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(Path(directory))
            driver = ExternalDriver(ExternalChromiumConnection())
            manager._playwright = cast("Playwright", driver)
            entered = asyncio.Event()
            release = asyncio.Event()

            async def stalled_stop() -> None:
                entered.set()
                await release.wait()

            driver.stop.side_effect = stalled_stop
            cleanup = asyncio.create_task(manager._stop_runtime(stop_display=False))
            await asyncio.wait_for(entered.wait(), timeout=1)
            cleanup.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await cleanup
            self.assertIsNotNone(manager._driver_stop_task)
            manager._control = cast(BrowserControlClient, ProcessControl())
            with patch("playwright.async_api.async_playwright") as factory:
                recovery = asyncio.create_task(manager._ensure_started())
                await asyncio.sleep(0.02)
                factory.assert_not_called()
                self.assertFalse(recovery.done())
                release.set()
                # Replacement is permitted only after the previous driver stops.
                factory.return_value = ExternalDriver(ExternalChromiumConnection())
                with patch.object(manager, "_set_chromium_developer_state", new_callable=AsyncMock):
                    await recovery
                factory.assert_called_once()
            driver.stop.assert_awaited_once()
            await manager.shutdown()

    async def test_repeated_cancelled_cdp_attach_reaps_real_node_driver(self) -> None:
        # Regression: cancellation during connect_over_cdp used to bypass the
        # Exception handler and strand one real Node process per attempt.
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(Path(directory))
            manager._control = cast(BrowserControlClient, ProcessControl())
            received = asyncio.Event()
            release = asyncio.Event()
            owners: list[PlaywrightContextManager] = []
            tasks: set[asyncio.Task[None]] = set()

            async def stall(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
                try:
                    await reader.read(4096)
                    received.set()
                    await release.wait()
                finally:
                    writer.close()
                    await writer.wait_closed()

            def accept(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
                task = asyncio.create_task(stall(reader, writer))
                tasks.add(task)
                task.add_done_callback(tasks.discard)

            def factory() -> PlaywrightContextManager:
                owner = async_playwright()
                owners.append(owner)
                return owner

            server = await asyncio.start_server(accept, "127.0.0.1", 0)
            manager.cdp_url = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
            try:
                with patch("playwright.async_api.async_playwright", side_effect=factory):
                    for _ in range(3):
                        received.clear()
                        startup = asyncio.create_task(manager._start_with_timeout())
                        try:
                            await asyncio.wait_for(received.wait(), timeout=10)
                            proc = cast(PipeTransport, owners[-1]._connection._transport)._proc
                            self.assertIsNone(proc.returncode)
                        finally:
                            startup.cancel()
                            with self.assertRaises(asyncio.CancelledError):
                                await startup
                        self.assertEqual(proc.returncode, 0)
                        self.assertIsNone(manager._playwright)
                        self.assertIsNone(manager._driver_stop_task)
                self.assertEqual(len(owners), 3)
            finally:
                release.set()
                server.close()
                await server.wait_closed()
                await asyncio.gather(*tasks, return_exceptions=True)
                # Also reap any orphan when running this regression against the old code.
                for owner in owners:
                    proc = cast(PipeTransport, owner._connection._transport)._proc
                    if proc.returncode is None:
                        proc.kill()
                        await proc.wait()

    async def test_status_does_not_hide_an_unresponsive_tab(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(Path(directory))
            manager._control = cast(BrowserControlClient, ProcessControl())
            context = MagicMock()
            tab = MagicMock()
            tab.is_closed.return_value = False
            context.pages = [tab]
            manager._context = cast("BrowserContext", context)
            with (
                patch.object(manager, "_cdp_reachable", new_callable=AsyncMock, return_value=True),
                patch.object(manager, "_context_usable", new_callable=AsyncMock, return_value=True),
                patch.object(manager, "_observed_runtime", new_callable=AsyncMock, return_value={}),
                patch.object(
                    manager,
                    "_register_page",
                    new_callable=AsyncMock,
                    side_effect=TimeoutError("CDP unresponsive"),
                ),
                self.assertRaisesRegex(TimeoutError, "CDP unresponsive"),
            ):
                await manager.status()

    async def test_invalid_navigation_url_is_a_warning_before_chromium_startup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(Path(directory))
            for invalid in ("example.com", "ftp://example.com", "http://[invalid"):
                with (
                    self.subTest(url=invalid),
                    patch.object(manager, "_ensure_started", new_callable=AsyncMock) as start,
                    self.assertRaises(BrowserRequestError) as raised,
                ):
                    await manager.open(invalid)
                self.assertIsInstance(raised.exception, ToolError)
                self.assertEqual(raised.exception.log_level, logging.WARNING)
                self.assertIn("browser URL must be absolute http(s)", str(raised.exception))
                start.assert_not_called()
        self.assertEqual(BrowserManager._url("https://example.com"), "https://example.com")

    async def test_stale_element_reference_is_actionable_info_not_error_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(Path(directory))
            page = MagicMock()
            locator = MagicMock()
            page.locator.return_value = locator
            with (
                patch.object(manager, "_page", new_callable=AsyncMock, return_value=page),
                patch.object(manager, "_require_agent_access"),
            ):
                for matches in (0, 2):
                    locator.count = AsyncMock(return_value=matches)
                    with (
                        self.subTest(matches=matches),
                        self.assertRaises(BrowserStaleStateError) as captured,
                    ):
                        await manager._locator("fixture", "e12")
                    self.assertIsInstance(captured.exception, ToolError)
                    self.assertEqual(captured.exception.log_level, logging.INFO)
                    self.assertIn("take a new browser_snapshot", str(captured.exception))

    async def test_missing_page_remains_actionable_tool_error_at_info_level(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(Path(directory))
            with (
                patch.object(manager, "_ensure_started", new_callable=AsyncMock),
                self.assertRaises(BrowserStaleStateError) as captured,
            ):
                await manager._page("not-registered")
            self.assertIsInstance(captured.exception, BrowserError)
            self.assertIsInstance(captured.exception, ToolError)
            self.assertEqual(captured.exception.log_level, logging.INFO)
            self.assertIn("browser_pages", str(captured.exception))
            self.assertIn("browser_open", str(captured.exception))

    async def test_click_blocked_by_overlay_is_actionable_warning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(Path(directory))
            manager.click_timeout_ms = 3500
            page, locator = MagicMock(), MagicMock()
            locator.click = AsyncMock(
                side_effect=PlaywrightTimeoutError(
                    "Locator.click: Timeout 3500ms exceeded. subtree intercepts pointer events"
                )
            )
            with (
                patch.object(
                    manager, "_locator", new_callable=AsyncMock, return_value=(page, locator)
                ),
                self.assertRaises(BrowserRequestError) as captured,
            ):
                await manager.click("tab-id", "e12")
            self.assertEqual(captured.exception.log_level, logging.WARNING)
            self.assertIn("close the overlay", str(captured.exception))
            locator.click.assert_awaited_once_with(timeout=3500)
            self.assertNotIn("force", str(captured.exception))

    async def test_click_timeout_without_overlay_remains_real_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(Path(directory))
            page, locator = MagicMock(), MagicMock()
            timeout = PlaywrightTimeoutError("Locator.click: Timeout 1000ms exceeded")
            locator.click = AsyncMock(side_effect=timeout)
            with (
                patch.object(
                    manager, "_locator", new_callable=AsyncMock, return_value=(page, locator)
                ),
                self.assertRaises(PlaywrightTimeoutError) as raised,
            ):
                await manager.click("tab-id", "e12")
            self.assertIs(raised.exception, timeout)
            locator.click.assert_awaited_once_with(timeout=1000)

    async def test_click_uses_configured_deadline_without_forced_click(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(Path(directory))
            manager.click_timeout_ms = 2400
            page, locator = MagicMock(), MagicMock()
            locator.click = AsyncMock()
            page.wait_for_timeout = AsyncMock()
            with (
                patch.object(
                    manager, "_locator", new_callable=AsyncMock, return_value=(page, locator)
                ),
                patch.object(
                    manager, "_summary", new_callable=AsyncMock, return_value={"page_id": "tab-id"}
                ),
            ):
                result = await manager.click("tab-id", "e12")
            self.assertEqual(result["page_id"], "tab-id")
            locator.click.assert_awaited_once_with(timeout=2400)
            page.wait_for_timeout.assert_awaited_once_with(150)

    async def test_unattached_status_uses_external_owner_and_reports_disconnected_context(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(Path(directory))
            manager.cdp_connect_timeout_ms = 5_000
            manager._next_idle_reconnect_at = 100_000.0
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
            self.assertEqual(remote.attachments, [])
            self.assertEqual(remote.connection_options, [])
            self.assertEqual(manager._next_idle_reconnect_at, 100_000.0)
            self.assertTrue(status["process_running"])
            self.assertTrue(status["cdp_reachable"])
            self.assertFalse(status["context_usable"])
            self.assertFalse(status["running"])
            self.assertFalse(status["manually_stopped"])
            self.assertEqual(status["pages"], [])
            self.assertEqual(requests, [("POST", "/RPC2"), ("GET", "/json/version")])

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
                patch.object(
                    manager,
                    "_target_id",
                    new_callable=AsyncMock,
                    side_effect=lambda tab: f"target-{id(tab)}",
                ),
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
                patch.object(
                    manager,
                    "_target_id",
                    new_callable=AsyncMock,
                    side_effect=lambda tab: f"target-{id(tab)}",
                ),
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
