from __future__ import annotations

import asyncio as asyncio
import contextlib as contextlib
import json as json
import shutil as shutil
import tempfile as tempfile
import time as time
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
from web_runtime.infrastructure.viewport_capture import capture_viewport

from .application.browser_readiness import ObserveBrowserReadiness as ObserveBrowserReadiness
from .application.developer_sync import ReconcileDeveloperSync as ReconcileDeveloperSync
from .browser_extensions import BrowserExtensionRegistry as BrowserExtensionRegistry
from .browser_extensions import DevExtension as DevExtension
from .browser_models import AgentAccessStatus as AgentAccessStatus
from .browser_models import BrowserDiagnostics as BrowserDiagnostics
from .browser_models import BrowserObservation as BrowserObservation
from .browser_models import BrowserPages as BrowserPages
from .browser_models import BrowserPreview as BrowserPreview
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
from .infrastructure.browser_environment import (
    BrowserProcessEnvironment as BrowserProcessEnvironment,
)
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
        developer_access_enabled: bool | None = None,
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
        # A Hand executor must never opt out of Chromium's process sandbox.
        # Docker cap_drop/read_only are not a replacement for browser isolation.
        unsafe = (
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-seccomp-filter-sandbox",
            "--disable-namespace-sandbox",
            "--disable-gpu-sandbox",
        )
        if any(arg.split("=", 1)[0] in unsafe for arg in self.chromium_args):
            raise BrowserError("Chromium sandbox-disabling arguments are prohibited")
        self.max_snapshot_text_chars = max_snapshot_text_chars
        self.max_snapshot_elements = max_snapshot_elements
        self._initialize_session_state()
        if developer_access_enabled is not None:
            if type(developer_access_enabled) is not bool:
                raise BrowserError("developer access policy must be boolean")
            self._policy.developer_access_enabled = developer_access_enabled
            self._persist_policy()

    def _initialize_session_state(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._browser_process: asyncio.subprocess.Process | None = None
        self._display_process: asyncio.subprocess.Process | None = None
        self._context: BrowserContext | None = None
        from hand_runtime.runtime_policy import runtime_policy

        self.runtime_limits = runtime_policy()
        self._page_activity: dict[str, float] = {}
        self._idle_task: asyncio.Task[None] | None = None
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

    def bind_unstarted_profile(self, profile_dir: Path, *, developer_access_enabled: bool) -> None:
        """Trusted Node composition can bind metadata prewarm to its first lease.

        No MCP tool calls this method. Once Chromium starts, changing actor
        requires destruction of the entire isolated child by its supervisor.
        """
        if self._browser_process is not None or self._context is not None or self._pages:
            raise BrowserError("cannot rebind an active browser profile")
        if type(developer_access_enabled) is not bool:
            raise BrowserError("developer access policy must be boolean")
        self.profile_dir = profile_dir.resolve(strict=False)
        self._policy_path = self.profile_dir / "koba-browser-policy.json"
        self._extension_registry = BrowserExtensionRegistry(
            self.profile_dir.parent / "dev-extensions.json", self.workspace.root
        )
        self._policy.agent_access_enabled, self._policy.color_scheme = True, "dark"
        self._page_labels, self._page_agent_access = {}, {}
        self._load_policy()
        self._policy.developer_access_enabled = developer_access_enabled
        self._persist_policy()

    def _browser_command(self) -> list[str]:
        command = [
            self.executable_path,
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

    def _browser_subprocess_environment(self) -> BrowserProcessEnvironment:
        # This reduces ambient credential inheritance but does NOT replace
        # separate UID/network/FS isolation: same-UID children can still read
        # other process state and private services in this controller container.
        root = self.profile_dir.parent
        environment = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": str(root),
            "XDG_CONFIG_HOME": str(root / "config"),
            "XDG_CACHE_HOME": str(root / "cache"),
            "TZ": self.timezone,
        }
        if self.posix_locale:
            environment["LANG"] = self.posix_locale
            environment["LC_ALL"] = self.posix_locale
        if not self.headless and self.display:
            environment["DISPLAY"] = self.display
        return BrowserProcessEnvironment(environment)

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
            env=self._browser_subprocess_environment().values,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        self._display_process = process
        try:
            await asyncio.sleep(0.15)
            if process.returncode is not None:
                raise BrowserError(f"Xvfb exited during startup: {process.returncode}")
        except BaseException:
            # Cancellation can arrive during the startup delay. Retaining an
            # untracked Xvfb here makes the next start collide with its display.
            self._display_process = None
            await self._terminate_display_process(process)
            raise
        return display

    def _requires_developer_startup_sync(self) -> bool:
        # A pristine Chrome profile has developer mode off and no userScripts
        # grants. Avoid booting chrome://extensions just to restate defaults.
        # Existing Chrome state or explicitly loaded extensions still requires
        # the full owner-policy synchronization, including when disabling it.
        if self._policy.developer_access_enabled or self._extension_registry.load_paths():
            return True
        return self.profile_dir.exists() and any(
            entry.name != "koba-browser-policy.json" for entry in self.profile_dir.iterdir()
        )

    async def _start_locked(self) -> None:
        if self._context is not None:
            return
        developer_sync_required = self._requires_developer_startup_sync()
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.workspace.ensure()
        for lock_name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            (self.profile_dir / lock_name).unlink(missing_ok=True)
        from playwright.async_api import async_playwright

        playwright = None
        process: asyncio.subprocess.Process | None = None
        browser: Browser | None = None
        try:
            await self._ensure_display_locked()
            playwright = await async_playwright().start()
            command = self._browser_command()
            process = await asyncio.create_subprocess_exec(
                *command,
                env=self._browser_subprocess_environment().values,
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
        except BaseException:
            if browser is not None:
                with contextlib.suppress(Exception):
                    await browser.close()
            await self._terminate_browser_process(process)
            display_process = self._display_process
            self._display_process = None
            await self._terminate_display_process(display_process)
            if playwright is not None:
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
        self._user_scripts_sync_error = ""
        if developer_sync_required:
            try:
                await self._set_chromium_developer_state(
                    self._policy.developer_access_enabled,
                    context=context,
                )
            except BrowserError as exc:
                self._user_scripts_sync_error = str(exc)
        context.on("page", self._on_context_page)

    def _on_context_page(self, page: Page) -> None:
        if (
            self.runtime_limits.web_max_tabs is not None
            and len(self._pages) >= self.runtime_limits.web_max_tabs
            and id(page) not in self._page_ids
        ):
            task = asyncio.create_task(page.close())
            task.add_done_callback(lambda item: item.exception() if not item.cancelled() else None)
            return
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
        self._page_activity[page_id] = time.monotonic()
        if self.runtime_limits.web_tab_idle_seconds is not None and (
            self._idle_task is None or self._idle_task.done()
        ):
            self._idle_task = asyncio.create_task(self._close_idle_pages())
        self._pages[page_id] = page
        self._page_ids[key] = page_id
        return page_id

    async def _close_idle_pages(self) -> None:
        while self._pages:
            idle = self.runtime_limits.web_tab_idle_seconds
            if idle is None:
                return
            await asyncio.sleep(min(5, idle))
            for page_id, last in list(self._page_activity.items()):
                if time.monotonic() - last >= idle:
                    page = self._pages.get(page_id)
                    if page is not None:
                        with contextlib.suppress(Exception):
                            await page.close()
                        self._forget_page(page_id)

    def _require_tab_capacity(self) -> None:
        maximum = self.runtime_limits.web_max_tabs
        if (
            maximum is not None
            and sum(not page.is_closed() for page in self._pages.values()) >= maximum
        ):
            raise BrowserError(f"Browser tab limit reached ({maximum}); close an existing tab")

    def _forget_page(self, page_id: str) -> None:
        self._page_activity.pop(page_id, None)
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
        self._page_activity[page_id] = time.monotonic()
        return page

    async def diagnostics(self) -> BrowserDiagnostics:
        self.profile_dir.parent.mkdir(parents=True, exist_ok=True)

        async def run(*args: str) -> tuple[int, str, str]:
            process = await asyncio.create_subprocess_exec(
                self.executable_path,
                *args,
                env=self._browser_subprocess_environment().values,
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
        return BrowserPages(
            count=len(status.pages),
            pages=status.pages,
            can_reopen_closed_tab=bool(self._closed_pages),
        )

    async def upload(self, page_id: str, ref: str, workspace_path: str) -> PageSummary:
        page, locator = await self._locator(page_id, ref)
        with self.workspace.upload_source(workspace_path) as source:
            if not source.is_file():
                raise BrowserError(f"upload path is not a file: {workspace_path}")
            await locator.set_input_files(str(source))
            result = await self._summary(page_id, page)
            result.workspace_path = self.workspace.transfer_relative(workspace_path, source)
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
        with self.workspace.download_target(workspace_path, overwrite=overwrite) as target:
            if target.exists() and not overwrite:
                raise BrowserError(f"destination already exists: {workspace_path}")
            target.parent.mkdir(parents=True, exist_ok=True)
            async with page.expect_download() as download_info:
                await locator.click()
            download = await download_info.value
            await download.save_as(str(target))
        result = self.workspace.info(self.workspace.transfer_relative(workspace_path, target))
        return BrowserDownload(result, download.suggested_filename)

    async def preview(self, page_id: str) -> BrowserPreview:
        """Bounded in-memory viewport image; current page access is mandatory."""
        self._require_agent_access(page_id)
        page = await self._page(page_id)
        image = await capture_viewport(page)
        return BrowserPreview(
            page_id=page_id,
            url=page.url,
            title=await page.title(),
            mime_type="image/png",
            data_base64=image,
        )

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
        with self.workspace.download_target(workspace_path, overwrite=overwrite) as target:
            if target.exists() and not overwrite:
                raise BrowserError(f"destination already exists: {workspace_path}")
            target.parent.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(target), full_page=full_page)
        return self.workspace.info(self.workspace.transfer_relative(workspace_path, target))

    async def forward(self, page_id: str) -> PageSummary:
        self._require_agent_access(page_id)
        page = await self._page(page_id)
        await page.go_forward(wait_until="domcontentloaded")
        return await self._summary(page_id, page)

    async def close_page(self, page_id: str) -> ClosedPage:
        self._require_agent_access(page_id)
        page = await self._page(page_id)
        summary = await self._summary(page_id, page)
        await page.close()
        self._remember_closed_page(summary)
        self._forget_page(page_id)
        return ClosedPage(page_id=page_id, closed=True)

    async def operator_reopen_closed_page(self, owner_token: str) -> PageSummary:
        self._require_operator(owner_token)
        result = await self._restore_closed_page()
        async with self._operator_lock:
            self._operator_pages[owner_token] = result.page_id
        return result

    def _remember_closed_page(self, summary: PageSummary) -> None:
        url = summary.url or "about:blank"
        if not url.startswith("devtools://"):
            self._closed_pages = self._closed_pages.remember(
                ClosedTab(url, summary.label or "", summary.page_agent_access)
            )

    async def reopen_closed_page(self) -> PageSummary:
        self._require_agent_access()
        if self._closed_pages and not self._closed_pages.entries[-1].page_agent_access:
            raise BrowserError("closed browser tab is not shared with agents")
        return await self._restore_closed_page()

    async def open_settings(self, section: str) -> PageSummary:
        self._require_agent_access()
        if section not in {"settings", "extensions"}:
            raise BrowserError("browser section must be settings or extensions")
        context = await self._ensure_started()
        self._require_tab_capacity()
        page = await context.new_page()
        page_id = self._register_page(page)
        await page.goto(self._operator_url(f"chrome://{section}/"), wait_until="domcontentloaded")
        return await self._summary(page_id, page)

    async def _restore_closed_page(self) -> PageSummary:
        if not self._closed_pages:
            raise BrowserError("no recently closed browser tab")
        context = await self._ensure_started()
        self._require_tab_capacity()
        item = self._closed_pages.entries[-1]
        page = await context.new_page()
        page_id = self._register_page(page)
        url = item.url or "about:blank"
        try:
            if url != "about:blank":
                await page.goto(self._operator_url(url), wait_until="domcontentloaded")
        except BaseException:
            await page.close()
            self._forget_page(page_id)
            raise
        self._closed_pages = self._closed_pages.take_latest().history
        label = item.label or ""
        if label:
            self._page_labels[page_id] = label
        if not item.page_agent_access:
            self._page_agent_access[page_id] = False
        result = await self._summary(page_id, page)
        result.reopened = True
        return result

    async def operator_close_page(self, owner_token: str, page_id: str) -> ClosedPage:
        self._require_operator(owner_token)
        page = await self._page(page_id)
        summary = await self._summary(page_id, page)
        await page.close()
        self._remember_closed_page(summary)
        self._forget_page(page_id)
        async with self._operator_lock:
            if self._operator_pages.get(owner_token) == page_id:
                self._operator_pages[owner_token] = ""
        return ClosedPage(page_id=page_id, closed=True)
