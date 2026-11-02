from __future__ import annotations

import asyncio as asyncio
import contextlib as contextlib
import json as json
import shutil as shutil
import tempfile as tempfile
import uuid as uuid
from collections.abc import Awaitable as Awaitable
from collections.abc import Callable as Callable
from pathlib import Path as Path
from typing import TYPE_CHECKING as TYPE_CHECKING
from typing import Literal as Literal
from urllib.parse import urlsplit as urlsplit

if TYPE_CHECKING:
    from playwright.async_api import Browser as Browser
    from playwright.async_api import BrowserContext as BrowserContext
    from playwright.async_api import CDPSession as CDPSession
    from playwright.async_api import Locator as Locator
    from playwright.async_api import Page as Page
    from playwright.async_api import Playwright as Playwright

from modules.workspace_compat.domain.receipts import WorkspaceEntry as WorkspaceEntry
from modules.workspace_compat.legacy_store import WorkspaceFileStore as WorkspaceFileStore
from web_runtime.infrastructure.browser_operations import BrowserError as BrowserError
from web_runtime.infrastructure.browser_operations import BrowserOperations as _BrowserOperations

from .application.browser_readiness import ObserveBrowserReadiness as ObserveBrowserReadiness
from .application.developer_sync import ReconcileDeveloperSync as ReconcileDeveloperSync
from .browser_extensions import BrowserExtensionRegistry as BrowserExtensionRegistry
from .browser_extensions import DevExtension as DevExtension
from .browser_models import AgentAccessStatus as AgentAccessStatus
from .browser_models import BrowserDiagnostics as BrowserDiagnostics
from .browser_models import BrowserObservation as BrowserObservation
from .browser_models import BrowserPages as BrowserPages
from .browser_models import BrowserStatus as BrowserStatus
from .browser_models import Capabilities as Capabilities
from .browser_models import ChromiumDeveloperObservation as ChromiumDeveloperObservation
from .browser_models import CleanBrowserResult as CleanBrowserResult
from .browser_models import ClosedPage as ClosedPage
from .browser_models import DebugTarget as DebugTarget
from .browser_models import DeveloperAccessReceipt as DeveloperAccessReceipt
from .browser_models import DeveloperExtensionReceipt as DeveloperExtensionReceipt
from .browser_models import DeveloperSyncResult as DeveloperSyncResult
from .browser_models import Dimensions as Dimensions
from .browser_models import EmptyObservation as EmptyObservation
from .browser_models import OperatorLease as OperatorLease
from .browser_models import OperatorState as OperatorState
from .browser_models import PageSummary as PageSummary
from .browser_models import SnapshotElement as SnapshotElement
from .domain.browser_policy import BrowserPolicy as BrowserPolicy
from .domain.closed_tabs import ClosedTab as ClosedTab
from .domain.closed_tabs import ClosedTabs as ClosedTabs
from .domain.developer_sync import DeveloperSyncViolation as DeveloperSyncViolation
from .domain.developer_sync import ExtensionFailure as ExtensionFailure
from .domain.developer_sync import ExtensionSyncReport as ExtensionSyncReport
from .infrastructure.browser_policy import encode_browser_policy as encode_browser_policy
from .infrastructure.browser_policy import restore_browser_policy as restore_browser_policy
from .models import BrowserDownload as BrowserDownload

_REMOTE_DEBUGGING_HOST = "127.0.0.1"
_REMOTE_DEBUGGING_PORT = 9222


class BrowserManager(_BrowserOperations):
    def __init__(
        self,
        *,
        workspace: WorkspaceFileStore,
        profile_dir: Path,
        executable_path: str,
        headless: bool,
        timeout_ms: int,
        viewport_width: int,
        viewport_height: int,
        screen_width: int | None = None,
        screen_height: int | None = None,
        max_snapshot_text_chars: int,
        max_snapshot_elements: int,
        locale: str = "ru-RU",
        accept_language: str = "ru-RU,ru,en-US,en",
        display: str = ":99",
        color_depth: int = 24,
        xvfb_enabled: bool = True,
        timezone: str = "UTC",
        posix_locale: str = "ru_RU.UTF-8",
        chromium_args: tuple[str, ...] = (),
    ) -> None:
        self.workspace = workspace
        self.profile_dir = profile_dir.resolve(strict=False)
        self.executable_path = executable_path
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.viewport_width = viewport_width
        self.viewport_height = viewport_height
        self.screen_width = screen_width or viewport_width
        self.screen_height = screen_height or viewport_height
        self.locale = locale.strip()
        self.accept_language = accept_language.strip()
        self.display = display.strip()
        self.color_depth = color_depth
        self.xvfb_enabled = xvfb_enabled
        self.timezone = timezone.strip() or "UTC"
        self.posix_locale = posix_locale.strip()
        self.chromium_args = tuple(arg.strip() for arg in chromium_args if arg.strip())
        self.max_snapshot_text_chars = max_snapshot_text_chars
        self.max_snapshot_elements = max_snapshot_elements
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._browser_process: asyncio.subprocess.Process | None = None
        self._display_process: asyncio.subprocess.Process | None = None
        self._context: BrowserContext | None = None
        self._pages: dict[str, Page] = {}
        self._page_ids: dict[int, str] = {}
        self._start_lock = asyncio.Lock()
        self._reset_lock = asyncio.Lock()
        self._operator_lock = asyncio.Lock()
        self._operator_pages: dict[str, str] = {}
        self._policy_lock = asyncio.Lock()
        self._policy_path = self.profile_dir / "koba-browser-policy.json"
        self._policy = BrowserPolicy()
        self._privileged_access_hooks: list[Callable[[bool], Awaitable[None]]] = []
        self._restart_hooks: list[Callable[[], Awaitable[None]]] = []
        self._developer_backend_connected = False
        self._managed_user_scripts_extension_ids: set[str] = set()
        self._user_scripts_sync_error = ""
        self._extension_registry = BrowserExtensionRegistry(
            self.profile_dir.parent / "dev-extensions.json",
            self.workspace.root,
        )
        self._page_labels: dict[str, str] = {}
        self._page_agent_access: dict[str, bool] = {}
        self._closed_pages = ClosedTabs()
        self._load_policy()

    def _browser_command(self) -> list[str]:
        command = [
            self.executable_path,
            "--no-sandbox",
            f"--remote-debugging-address={_REMOTE_DEBUGGING_HOST}",
            f"--remote-debugging-port={_REMOTE_DEBUGGING_PORT}",
            f"--user-data-dir={self.profile_dir}",
            f"--window-size={self.viewport_width},{self.viewport_height}",
        ]
        command.extend(self.chromium_args)
        if self._policy.color_scheme == "dark" and "--force-dark-mode" not in command:
            command.append("--force-dark-mode")
        extension_paths = self._extension_registry.load_paths()
        if extension_paths:
            command.append(f"--load-extension={','.join(extension_paths)}")
        if self.locale:
            command.append(f"--lang={self.locale}")
        if self.accept_language:
            command.append(f"--accept-lang={self.accept_language}")
        if self.headless:
            command.append("--headless=new")
        command.append("about:blank")
        return command

    def _browser_process_command(self) -> list[str]:
        environment = ["/usr/bin/env"]
        if not self.headless and self.display:
            environment.append(f"DISPLAY={self.display}")
        if self.timezone:
            environment.append(f"TZ={self.timezone}")
        if self.posix_locale:
            environment.extend(
                [
                    f"LANG={self.posix_locale}",
                    f"LC_ALL={self.posix_locale}",
                ]
            )
        return [*environment, *self._browser_command()]

    async def _ensure_display_locked(self) -> str:
        if self.headless:
            return ""
        display = self.display
        if not display:
            raise BrowserError("headful Chromium requires a configured display")
        if not self.xvfb_enabled:
            return display
        process = self._display_process
        if process is not None and process.returncode is None:
            return display
        process = await asyncio.create_subprocess_exec(
            "Xvfb",
            display,
            "-screen",
            "0",
            f"{self.screen_width}x{self.screen_height}x{self.color_depth}",
            "-nolisten",
            "tcp",
            "-noreset",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.sleep(0.15)
        if process.returncode is not None:
            raise BrowserError(f"Xvfb exited during startup: {process.returncode}")
        self._display_process = process
        return display

    async def _start_locked(self) -> None:
        if self._context is not None:
            return
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.workspace.ensure()
        for lock_name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            (self.profile_dir / lock_name).unlink(missing_ok=True)
        from playwright.async_api import async_playwright

        await self._ensure_display_locked()
        playwright = await async_playwright().start()
        command = self._browser_process_command()
        process: asyncio.subprocess.Process | None = None
        browser: Browser | None = None
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await self._wait_for_debugging_endpoint(process)
            browser = await playwright.chromium.connect_over_cdp(
                f"http://{_REMOTE_DEBUGGING_HOST}:{_REMOTE_DEBUGGING_PORT}",
                timeout=10_000,
            )
            if not browser.contexts:
                raise BrowserError("Chromium exposed no persistent browser context")
            context = browser.contexts[0]
        except Exception:
            if browser is not None:
                with contextlib.suppress(Exception):
                    await browser.close()
            await self._terminate_browser_process(process)
            display_process = self._display_process
            self._display_process = None
            await self._terminate_display_process(display_process)
            await playwright.stop()
            raise
        context.set_default_timeout(self.timeout_ms)
        context.set_default_navigation_timeout(self.timeout_ms)
        self._playwright = playwright
        self._browser = browser
        self._browser_process = process
        self._context = context
        for page in context.pages:
            self._register_page(page)
            await self._apply_color_scheme(page)
        try:
            await self._set_chromium_developer_state(
                self._policy.developer_access_enabled,
                context=context,
            )
        except BrowserError as exc:
            self._user_scripts_sync_error = str(exc)
        else:
            self._user_scripts_sync_error = ""
        context.on("page", self._on_context_page)

    def _on_context_page(self, page: Page) -> None:
        self._register_page(page)
        task = asyncio.create_task(
            self._apply_color_scheme(page), name="browser-apply-color-scheme"
        )
        task.add_done_callback(lambda item: item.exception() if not item.cancelled() else None)

    def _register_page(self, page: Page) -> str:
        key = id(page)
        existing = self._page_ids.get(key)
        if existing:
            return existing
        page_id = f"page-{uuid.uuid4().hex[:10]}"
        self._pages[page_id] = page
        self._page_ids[key] = page_id
        return page_id

    def _forget_page(self, page_id: str) -> None:
        page = self._pages.pop(page_id, None)
        if page is not None:
            self._page_ids.pop(id(page), None)
        self._page_labels.pop(page_id, None)
        self._page_agent_access.pop(page_id, None)
        for owner_token, selected_page_id in list(self._operator_pages.items()):
            if selected_page_id == page_id:
                self._operator_pages[owner_token] = ""

    async def _page(self, page_id: str) -> Page:
        await self._ensure_started()
        page = self._pages.get(page_id)
        if page is None or page.is_closed():
            self._forget_page(page_id)
            raise BrowserError(f"browser page not found: {page_id}")
        return page

    async def diagnostics(self) -> BrowserDiagnostics:
        self.profile_dir.parent.mkdir(parents=True, exist_ok=True)

        async def run(*args: str) -> tuple[int, str, str]:
            process = await asyncio.create_subprocess_exec(
                self.executable_path,
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=20)
            except TimeoutError:
                process.kill()
                await process.wait()
                return -1, "", "timed out after 20s"
            return (
                int(process.returncode or 0),
                stdout.decode("utf-8", errors="replace")[-12000:],
                stderr.decode("utf-8", errors="replace")[-12000:],
            )

        version_code, version_stdout, version_stderr = await run("--version")
        with tempfile.TemporaryDirectory(
            prefix="browser-probe-",
            dir=self.profile_dir.parent,
        ) as temporary_profile:
            probe_code, probe_stdout, probe_stderr = await run(
                "--headless",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                f"--user-data-dir={temporary_profile}",
                "--dump-dom",
                "data:text/html,<title>KobaBrowserProbe</title><body>probe-ok</body>",
            )
        return BrowserDiagnostics(
            executable_path=self.executable_path,
            profile_dir=str(self.profile_dir),
            version_exit_code=version_code,
            version_stdout=version_stdout,
            version_stderr=version_stderr,
            probe_exit_code=probe_code,
            probe_stdout=probe_stdout,
            probe_stderr=probe_stderr,
        )

    async def pages(self) -> BrowserPages:
        status = await self.status()
        return BrowserPages(count=len(status.pages), pages=status.pages)

    async def upload(self, page_id: str, ref: str, workspace_path: str) -> PageSummary:
        page, locator = await self._locator(page_id, ref)
        source = self.workspace.path_for(workspace_path)
        if not source.is_file():
            raise BrowserError(f"upload path is not a file: {workspace_path}")
        await locator.set_input_files(str(source))
        result = await self._summary(page_id, page)
        result.workspace_path = self.workspace.relative(source)
        return result

    async def download(
        self,
        page_id: str,
        ref: str,
        workspace_path: str,
        *,
        overwrite: bool,
    ) -> BrowserDownload:
        page, locator = await self._locator(page_id, ref)
        target = self.workspace.target_path(workspace_path)
        if target.exists() and not overwrite:
            raise BrowserError(f"destination already exists: {workspace_path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        async with page.expect_download() as download_info:
            await locator.click()
        download = await download_info.value
        await download.save_as(str(target))
        result = self.workspace.info(self.workspace.relative(target))
        return BrowserDownload(result, download.suggested_filename)

    async def screenshot(
        self,
        page_id: str,
        workspace_path: str,
        *,
        full_page: bool,
        overwrite: bool,
    ) -> WorkspaceEntry:
        self._require_agent_access(page_id)
        page = await self._page(page_id)
        target = self.workspace.target_path(workspace_path)
        if target.exists() and not overwrite:
            raise BrowserError(f"destination already exists: {workspace_path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(target), full_page=full_page)
        return self.workspace.info(self.workspace.relative(target))

    async def close_page(self, page_id: str) -> ClosedPage:
        self._require_agent_access(page_id)
        page = await self._page(page_id)
        await page.close()
        self._forget_page(page_id)
        return ClosedPage(page_id=page_id, closed=True)

    async def operator_reopen_closed_page(self, owner_token: str) -> PageSummary:
        self._require_operator(owner_token)
        if not self._closed_pages:
            raise BrowserError("no recently closed browser tab")
        restored = self._closed_pages.take_latest()
        self._closed_pages = restored.history
        item = restored.tab
        context = await self._ensure_started()
        page = await context.new_page()
        page_id = self._register_page(page)
        url = item.url or "about:blank"
        if url != "about:blank":
            await page.goto(self._operator_url(url), wait_until="domcontentloaded")
        label = item.label
        if label:
            self._page_labels[page_id] = label
        if not item.page_agent_access:
            self._page_agent_access[page_id] = False
        async with self._operator_lock:
            self._operator_pages[owner_token] = page_id
        result = await self._summary(page_id, page)
        result.reopened = True
        return result

    async def operator_close_page(self, owner_token: str, page_id: str) -> ClosedPage:
        self._require_operator(owner_token)
        page = await self._page(page_id)
        summary = await self._summary(page_id, page)
        url = summary.url
        if not url.startswith("devtools://"):
            self._closed_pages = self._closed_pages.remember(
                ClosedTab(
                    url or "about:blank",
                    summary.label,
                    summary.page_agent_access,
                )
            )
        await page.close()
        self._forget_page(page_id)
        async with self._operator_lock:
            if self._operator_pages.get(owner_token) == page_id:
                self._operator_pages[owner_token] = ""
        return ClosedPage(page_id=page_id, closed=True)
