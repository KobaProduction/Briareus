from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, CDPSession, Locator, Page, Playwright

from web_runtime.application.browser_readiness import ObserveBrowserReadiness
from web_runtime.browser_extensions import BrowserExtensionRegistry, DevExtension
from web_runtime.browser_models import (
    AgentAccessStatus,
    BrowserObservation,
    BrowserStatus,
    Capabilities,
    CleanBrowserResult,
    DebugTarget,
    DeveloperAccessReceipt,
    DeveloperExtensionReceipt,
    DeveloperSyncResult,
    Dimensions,
    EmptyObservation,
    OperatorLease,
    OperatorState,
    PageSummary,
    SnapshotElement,
)
from web_runtime.domain.browser_policy import BrowserPolicy
from web_runtime.domain.closed_tabs import ClosedTabs
from web_runtime.infrastructure.browser_policy import encode_browser_policy, restore_browser_policy

from .browser_developer_sync import synchronize_developer_state
from .browser_errors import BrowserError as BrowserError
from .browser_page_lifecycle import (
    clean_operator_browser,
    create_operator_page,
    navigate_page,
)

_REMOTE_DEBUGGING_HOST = "127.0.0.1"
_REMOTE_DEBUGGING_PORT = 9222


class BrowserOperations(ABC):
    """Common browser mechanisms; owner constructors and policy hooks are required."""

    _browser: Browser | None
    _browser_process: asyncio.subprocess.Process | None
    _closed_pages: ClosedTabs
    _context: BrowserContext | None
    _developer_backend_connected: bool
    _display_process: asyncio.subprocess.Process | None
    _extension_registry: BrowserExtensionRegistry
    _managed_user_scripts_extension_ids: set[str]
    _operator_lock: asyncio.Lock
    _operator_pages: dict[str, str]
    _page_agent_access: dict[str, bool]
    _page_ids: dict[int, str]
    _page_labels: dict[str, str]
    _pages: dict[str, Page]
    _playwright: Playwright | None
    _policy: BrowserPolicy
    _policy_lock: asyncio.Lock
    _policy_path: Path
    _privileged_access_hooks: list[Callable[[bool], Awaitable[None]]]
    _reset_lock: asyncio.Lock
    _restart_hooks: list[Callable[[], Awaitable[None]]]
    _start_lock: asyncio.Lock
    _user_scripts_sync_error: str
    accept_language: str
    chromium_args: tuple[str, ...]
    display: str
    executable_path: str
    headless: bool
    locale: str
    max_snapshot_elements: int
    max_snapshot_text_chars: int
    posix_locale: str
    profile_dir: Path
    screen_height: int
    screen_width: int
    timeout_ms: int
    timezone: str
    viewport_height: int
    viewport_width: int
    xvfb_enabled: bool

    @abstractmethod
    async def _page(self, page_id: str) -> Page: ...

    @abstractmethod
    def _register_page(self, page: Page) -> str: ...

    async def _set_chromium_developer_state(
        self,
        enabled: bool,
        *,
        extension_ids: list[str] | None = None,
        update_profile_mode: bool = True,
        context: BrowserContext | None = None,
    ) -> DeveloperSyncResult:
        return await synchronize_developer_state(
            self,
            enabled,
            extension_ids=extension_ids,
            update_profile_mode=update_profile_mode,
            context=context,
        )

    def _require_tab_capacity(self) -> None:
        """Owner adapters enforce their configured page capacity before allocation."""
        return

    @abstractmethod
    def _forget_page(self, page_id: str) -> None: ...

    @abstractmethod
    async def _start_locked(self) -> None: ...

    def _load_policy(self) -> None:
        try:
            restore_browser_policy(self._policy, self._policy_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return

    def _persist_policy(self) -> None:
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        temporary = self._policy_path.with_suffix(".tmp")
        temporary.write_text(encode_browser_policy(self._policy), encoding="utf-8")
        temporary.replace(self._policy_path)

    @property
    def developer_access_enabled(self) -> bool:
        return self._policy.developer_access_enabled

    @property
    def developer_access_effective(self) -> bool:
        return self._policy.agent_access_enabled and self._policy.developer_access_enabled

    def require_developer_access(self) -> None:
        if not self._policy.agent_access_enabled:
            raise BrowserError("browser agent access is disabled by operator")
        if not self._policy.developer_access_enabled:
            raise BrowserError(
                "browser developer access is disabled by operator; "
                "use browser_status to inspect the current access mode"
            )

    @property
    def developer_backend_connected(self) -> bool:
        return self._developer_backend_connected

    def set_developer_backend_connected(self, connected: bool) -> None:
        self._developer_backend_connected = bool(connected)

    def add_privileged_access_hook(
        self,
        hook: Callable[[bool], Awaitable[None]],
    ) -> None:
        self._privileged_access_hooks.append(hook)

    def add_restart_hook(self, hook: Callable[[], Awaitable[None]]) -> None:
        self._restart_hooks.append(hook)

    async def _notify_restart(self) -> None:
        for hook in list(self._restart_hooks):
            with contextlib.suppress(Exception):
                await hook()

    async def _notify_privileged_access(self) -> None:
        enabled = self.developer_access_effective
        for hook in list(self._privileged_access_hooks):
            with contextlib.suppress(Exception):
                await hook(enabled)

    def _require_operator(self, owner_token: str) -> None:
        if not owner_token or owner_token not in self._operator_pages:
            raise BrowserError("browser operator session is not active")

    def _agent_access_allowed(self, page_id: str = "") -> bool:
        if not self._policy.agent_access_enabled:
            return False
        return not (page_id and not self._page_agent_access.get(page_id, True))

    def _require_agent_access(self, page_id: str = "") -> None:
        if not self._policy.agent_access_enabled:
            raise BrowserError("browser agent access is disabled by operator")
        if page_id and not self._page_agent_access.get(page_id, True):
            raise BrowserError(f"browser page is locked by operator: {page_id}")

    async def _wait_for_debugging_endpoint(self, process: asyncio.subprocess.Process) -> None:
        deadline = asyncio.get_running_loop().time() + 12.0
        last_error = ""
        while asyncio.get_running_loop().time() < deadline:
            if process.returncode is not None:
                raise BrowserError(
                    f"Chromium exited before remote debugging became ready: {process.returncode}"
                )
            try:
                reader, writer = await asyncio.open_connection(
                    _REMOTE_DEBUGGING_HOST,
                    _REMOTE_DEBUGGING_PORT,
                )
                writer.close()
                await writer.wait_closed()
                del reader
                return
            except OSError as exc:
                last_error = str(exc)
                await asyncio.sleep(0.1)
        raise BrowserError(
            "Chromium remote debugging endpoint did not become ready"
            + (f": {last_error}" if last_error else "")
        )

    async def _cdp_reachable(self) -> bool:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(_REMOTE_DEBUGGING_HOST, _REMOTE_DEBUGGING_PORT),
                timeout=1.0,
            )
            request = (
                f"GET /json/version HTTP/1.1\r\n"
                f"Host: {_REMOTE_DEBUGGING_HOST}:{_REMOTE_DEBUGGING_PORT}\r\n"
                "Connection: close\r\n\r\n"
            )
            writer.write(request.encode("ascii"))
            await writer.drain()
            status_line = await asyncio.wait_for(reader.readline(), timeout=1.0)
            writer.close()
            await writer.wait_closed()
            return b" 200 " in status_line
        except (OSError, TimeoutError):
            return False

    async def _context_usable(self) -> bool:
        browser = self._browser
        context = self._context
        if browser is None or context is None or not browser.is_connected():
            return False
        try:
            await asyncio.wait_for(context.cookies(), timeout=2.0)
        except Exception:
            return False
        return True

    async def _terminate_browser_process(
        self,
        process: asyncio.subprocess.Process | None,
    ) -> None:
        if process is None or process.returncode is not None:
            return
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except TimeoutError:
            process.kill()
            await process.wait()

    async def _terminate_display_process(
        self,
        process: asyncio.subprocess.Process | None,
    ) -> None:
        if process is None or process.returncode is not None:
            return
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except TimeoutError:
            process.kill()
            await process.wait()

    async def _ensure_started(self) -> BrowserContext:
        if self._context is not None and await self._context_usable():
            return self._context
        if self._context is not None or (
            self._browser_process is not None and self._browser_process.returncode is None
        ):
            await self.restart()
        elif self._context is None:
            async with self._start_lock:
                await self._start_locked()
        if self._context is None or not await self._context_usable():
            raise BrowserError("browser failed to start a usable context")
        return self._context

    async def _stop_runtime(self, *, stop_display: bool) -> None:
        context = self._context
        browser = self._browser
        process = self._browser_process
        playwright = self._playwright
        display_process = self._display_process if stop_display else None
        self._context = None
        self._browser = None
        self._browser_process = None
        self._playwright = None
        if stop_display:
            self._display_process = None

        if context is not None:
            with contextlib.suppress(Exception):
                await context.close()
        if browser is not None:
            with contextlib.suppress(Exception):
                await browser.close()
        await self._terminate_browser_process(process)
        if stop_display:
            await self._terminate_display_process(display_process)
        if playwright is not None:
            with contextlib.suppress(Exception):
                await playwright.stop()

        self._pages.clear()
        self._page_ids.clear()
        self._page_labels.clear()
        self._page_agent_access.clear()
        async with self._operator_lock:
            for token in list(self._operator_pages):
                self._operator_pages[token] = ""

    async def restart(self) -> BrowserStatus:
        """Restart Chromium without deleting the persistent browser profile."""
        async with self._reset_lock:
            await self._notify_restart()
            self._developer_backend_connected = False
            await self._stop_runtime(stop_display=False)
            async with self._start_lock:
                await self._start_locked()
        return await self.status()

    async def recover_if_broken(self) -> bool:
        process_running = (
            self._browser_process is not None and self._browser_process.returncode is None
        )
        if process_running and await self._cdp_reachable() and await self._context_usable():
            return False
        await self.restart()
        return True

    def record_dev_extension(self, extension_id: str, path: str) -> None:
        self._extension_registry.record(extension_id, path)

    def forget_dev_extension(self, extension_id: str) -> None:
        self._extension_registry.remove(extension_id)

    def dev_extensions(self) -> tuple[DevExtension, ...]:
        return self._extension_registry.items()

    def managed_extension_ids(self) -> frozenset[str]:
        return frozenset(self._managed_user_scripts_extension_ids)

    def replace_managed_extension_ids(self, values: frozenset[str]) -> None:
        self._managed_user_scripts_extension_ids = set(values)

    async def sync_dev_extension_user_scripts(self, extension_id: str) -> DeveloperExtensionReceipt:
        result = await self._set_chromium_developer_state(
            self._policy.developer_access_enabled,
            extension_ids=[extension_id],
            update_profile_mode=False,
        )
        return DeveloperExtensionReceipt(
            extension_id=extension_id,
            user_scripts_managed=extension_id in self._managed_user_scripts_extension_ids,
            in_developer_mode=result.in_developer_mode,
            user_scripts_enabled=result.user_scripts_enabled,
            user_scripts_extension_count=result.user_scripts_extension_count,
            extensions=result.extensions,
        )

    async def _apply_color_scheme(self, page: Page) -> None:
        scheme = None if self._policy.color_scheme == "system" else self._policy.color_scheme
        try:
            await page.emulate_media(color_scheme=scheme)
        except Exception as exc:
            raise BrowserError(f"browser color scheme update failed: {exc}") from exc

    async def set_color_scheme(self, color_scheme: str) -> BrowserStatus:
        normalized = color_scheme.strip().casefold()
        if normalized == "system":
            self._policy.color_scheme = "system"
        elif normalized == "light":
            self._policy.color_scheme = "light"
        elif normalized == "dark":
            self._policy.color_scheme = "dark"
        else:
            raise BrowserError("browser color scheme must be system, light, or dark")
        await asyncio.to_thread(self._persist_policy)
        context = await self._ensure_started()
        updated = 0
        for page in list(context.pages):
            if page.is_closed():
                continue
            await self._apply_color_scheme(page)
            updated += 1
        result = await self.status()
        result.updated_pages = updated
        result.native_ui_restart_required = True
        return result

    async def debug_target(self, page_id: str) -> DebugTarget:
        self._require_agent_access(page_id)
        context = await self._ensure_started()
        page = await self._page(page_id)
        if page.url.startswith("devtools://"):
            raise BrowserError("select an application tab for remote debugging")
        session = await context.new_cdp_session(page)
        try:
            info = await session.send("Target.getTargetInfo")
        finally:
            await session.detach()
        target_info = info.get("targetInfo")
        target_id = str(target_info.get("targetId") or "") if isinstance(target_info, dict) else ""
        if not target_id:
            raise BrowserError("selected browser tab has no remote debugging target")
        return DebugTarget(
            page_id=page_id, target_id=target_id, title=await page.title(), url=page.url
        )

    @staticmethod
    def _url(value: str) -> str:
        value = value.strip()
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise BrowserError("browser URL must be absolute http(s)")
        return value

    @classmethod
    def _operator_url(cls, value: str) -> str:
        value = value.strip()
        parsed = urlsplit(value)
        # Settings navigation adds subpaths and search parameters. Retain the
        # same exact built-in hosts; other chrome pages remain unavailable.
        if parsed.scheme == "chrome" and parsed.netloc in {"settings", "extensions"}:
            return value
        if value in {"chrome://version", "chrome://version/"}:
            return value
        return cls._url(value)

    async def _summary(self, page_id: str, page: Page) -> PageSummary:
        return PageSummary(
            page_id=page_id,
            label=self._page_labels.get(page_id, ""),
            page_agent_access=self._page_agent_access.get(page_id, True),
            agent_access=self._agent_access_allowed(page_id),
            url=page.url,
            title=await page.title(),
        )

    async def _agent_summary(self, page_id: str, page: Page) -> PageSummary:
        if self._agent_access_allowed(page_id):
            return await self._summary(page_id, page)
        return PageSummary(
            page_id=page_id,
            label=self._page_labels.get(page_id, ""),
            page_agent_access=self._page_agent_access.get(page_id, True),
            agent_access=False,
            locked=True,
            url="",
            title="",
        )

    async def _observed_runtime(self) -> BrowserObservation | EmptyObservation:
        context = self._context
        if context is None or not await self._context_usable():
            return EmptyObservation()
        pages = [page for page in context.pages if not page.is_closed()]
        if not pages:
            return EmptyObservation()
        page = pages[0]
        try:
            observed = await asyncio.wait_for(
                page.evaluate(
                    """() => {
                      const glInfo = (kind) => {
                        const canvas = document.createElement('canvas');
                        const gl = canvas.getContext(kind);
                        if (!gl) return null;
                        const ext = gl.getExtension('WEBGL_debug_renderer_info');
                        return {
                          vendor: ext ? gl.getParameter(ext.UNMASKED_VENDOR_WEBGL) : '',
                          renderer: ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : ''
                        };
                      };
                      return {
                        user_agent: navigator.userAgent,
                        user_agent_brands: navigator.userAgentData?.brands ?? [],
                        language: navigator.language,
                        languages: navigator.languages,
                        intl_locale: Intl.DateTimeFormat().resolvedOptions().locale,
                        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
                        webdriver: navigator.webdriver,
                        webgl: glInfo('webgl'),
                        webgl2: glInfo('webgl2'),
                        screen: {width: screen.width, height: screen.height}
                      };
                    }"""
                ),
                timeout=3.0,
            )
        except Exception:
            return EmptyObservation()
        try:
            return BrowserObservation.model_validate(observed)
        except ValueError:
            return EmptyObservation()

    def status_needs_start(self) -> bool:
        return self._context is None and self._browser_process is None

    async def start_status_runtime(self) -> None:
        await self._ensure_started()

    def status_process_running(self) -> bool:
        return self._browser_process is not None and self._browser_process.returncode is None

    def status_disconnect_developer(self) -> None:
        self._developer_backend_connected = False

    async def _status_pages(self, context_usable: bool) -> list[PageSummary]:
        if not context_usable or self._context is None:
            return []
        return [
            await self._agent_summary(self._register_page(page), page)
            for page in list(self._context.pages)
            if not page.is_closed()
        ]

    async def status(self) -> BrowserStatus:
        readiness = await ObserveBrowserReadiness(self).execute()
        pages = await self._status_pages(readiness.context_usable)
        observed = (
            await self._observed_runtime() if readiness.context_usable else EmptyObservation()
        )
        return BrowserStatus(
            running=readiness.running,
            process_running=readiness.process_running,
            cdp_reachable=readiness.cdp_reachable,
            context_usable=readiness.context_usable,
            agent_access_enabled=self._policy.agent_access_enabled,
            developer_access_enabled=self._policy.developer_access_enabled,
            developer_access_effective=self.developer_access_effective,
            developer_backend="chrome-devtools-mcp",
            developer_backend_connected=self._developer_backend_connected,
            headless=self.headless,
            browser="chromium",
            capabilities=Capabilities(set_viewport=True, set_theme=True, remote_devtools=True),
            color_scheme=self._policy.color_scheme,
            locale=self.locale,
            accept_language=self.accept_language,
            display="" if self.headless else self.display,
            xvfb_enabled=self.xvfb_enabled,
            timezone=self.timezone,
            posix_locale=self.posix_locale,
            chromium_args=list(self.chromium_args),
            executable_path=self.executable_path,
            profile_dir=str(self.profile_dir),
            dev_extensions=self.dev_extensions(),
            managed_user_scripts_extension_count=len(self._managed_user_scripts_extension_ids),
            user_scripts_follow_developer_access=True,
            user_scripts_sync_error=self._user_scripts_sync_error,
            observed=observed,
            page_count=len(pages),
            pages=pages,
        )

    async def open(self, url: str, page_id: str = "") -> PageSummary:
        return await navigate_page(self, url, page_id)

    async def snapshot(
        self,
        page_id: str,
        *,
        max_text_chars: int | None = None,
        max_elements: int | None = None,
    ) -> PageSummary:
        self._require_agent_access(page_id)
        page = await self._page(page_id)
        text_limit = min(
            max_text_chars or self.max_snapshot_text_chars,
            self.max_snapshot_text_chars,
        )
        element_limit = min(
            max_elements or self.max_snapshot_elements,
            self.max_snapshot_elements,
        )
        if text_limit <= 0 or element_limit <= 0:
            raise BrowserError("snapshot limits must be positive")
        text = await page.locator("body").inner_text(timeout=self.timeout_ms)
        text_truncated = len(text) > text_limit
        if text_truncated:
            text = text[:text_limit]
        raw_elements: object = await page.evaluate(
            """
            (limit) => {
              document.querySelectorAll('[data-koba-ref]').forEach(
                (el) => el.removeAttribute('data-koba-ref')
              );
              const selector = [
                'a[href]', 'button', 'input', 'textarea', 'select', 'summary',
                '[role="button"]', '[role="link"]', '[role="checkbox"]',
                '[role="radio"]', '[role="tab"]', '[contenteditable="true"]'
              ].join(',');
              const nodes = Array.from(document.querySelectorAll(selector))
                .filter((el) => {
                  if (el.matches('input[type="file"]')) return true;
                  const style = window.getComputedStyle(el);
                  return style.visibility !== 'hidden' && style.display !== 'none' &&
                    el.getClientRects().length > 0;
                })
                .slice(0, limit);
              return nodes.map((el, index) => {
                const ref = `e${index + 1}`;
                el.setAttribute('data-koba-ref', ref);
                const text = (el.innerText || el.textContent || '').trim();
                const inputType = (el.getAttribute('type') || '').toLowerCase();
                const value = inputType === 'password'
                  ? '<redacted>'
                  : ('value' in el ? String(el.value || '') : '');
                return {
                  ref,
                  tag: el.tagName.toLowerCase(),
                  role: el.getAttribute('role') || '',
                  type: el.getAttribute('type') || '',
                  name: el.getAttribute('aria-label') || el.getAttribute('title') ||
                    el.getAttribute('placeholder') || text.slice(0, 240),
                  href: el.getAttribute('href') || '',
                  value: value.slice(0, 240),
                  disabled: Boolean(el.disabled),
                };
              });
            }
            """,
            element_limit,
        )
        if not isinstance(raw_elements, list):
            raise BrowserError("browser snapshot returned invalid element data")
        elements = [SnapshotElement.model_validate(item) for item in raw_elements]
        summary = await self._summary(page_id, page)
        summary.text = text
        summary.text_truncated = text_truncated
        summary.elements = elements
        summary.element_count = len(elements)
        return summary

    async def _locator(self, page_id: str, ref: str) -> tuple[Page, Locator]:
        self._require_agent_access(page_id)
        page = await self._page(page_id)
        ref = ref.strip()
        if not ref:
            raise BrowserError("element ref is required")
        locator = page.locator(f'[data-koba-ref="{ref}"]')
        if await locator.count() != 1:
            raise BrowserError(
                f"element ref {ref!r} is stale or ambiguous; take a new browser_snapshot"
            )
        return page, locator

    async def click(self, page_id: str, ref: str) -> PageSummary:
        page, locator = await self._locator(page_id, ref)
        await locator.click()
        await page.wait_for_timeout(150)
        return await self._summary(page_id, page)

    async def fill(self, page_id: str, ref: str, value: str, *, press_enter: bool) -> PageSummary:
        page, locator = await self._locator(page_id, ref)
        await locator.fill(value)
        if press_enter:
            await locator.press("Enter")
            await page.wait_for_timeout(150)
        return await self._summary(page_id, page)

    async def press(self, page_id: str, ref: str, key: str) -> PageSummary:
        page, locator = await self._locator(page_id, ref)
        await locator.press(key)
        await page.wait_for_timeout(100)
        return await self._summary(page_id, page)

    async def select_option(self, page_id: str, ref: str, value: str) -> PageSummary:
        page, locator = await self._locator(page_id, ref)
        selected = await locator.select_option(value=value)
        result = await self._summary(page_id, page)
        result.selected = selected
        return result

    async def wait(
        self,
        page_id: str,
        *,
        state: str,
        timeout_seconds: float,
    ) -> PageSummary:
        self._require_agent_access(page_id)
        page = await self._page(page_id)
        normalized = state.strip().casefold()
        load_state: Literal["load", "domcontentloaded", "networkidle"]
        if normalized == "load":
            load_state = "load"
        elif normalized == "domcontentloaded":
            load_state = "domcontentloaded"
        elif normalized == "networkidle":
            load_state = "networkidle"
        else:
            raise BrowserError("wait state must be load, domcontentloaded, or networkidle")
        if not 0 < timeout_seconds <= 120:
            raise BrowserError("timeout_seconds must be between 0 and 120")
        await page.wait_for_load_state(load_state, timeout=timeout_seconds * 1000)
        return await self._summary(page_id, page)

    async def back(self, page_id: str) -> PageSummary:
        self._require_agent_access(page_id)
        page = await self._page(page_id)
        await page.go_back(wait_until="domcontentloaded")
        return await self._summary(page_id, page)

    async def reload(self, page_id: str) -> PageSummary:
        self._require_agent_access(page_id)
        page = await self._page(page_id)
        response = await page.reload(wait_until="domcontentloaded")
        result = await self._summary(page_id, page)
        result.http_status = response.status if response is not None else None
        return result

    async def set_viewport(self, page_id: str, width: int, height: int) -> PageSummary:
        self._require_agent_access(page_id)
        if not 320 <= width <= 7680 or not 240 <= height <= 4320:
            raise BrowserError("browser viewport must be between 320x240 and 7680x4320")
        page = await self._page(page_id)
        if page.is_closed():
            raise BrowserError(f"browser page is closed: {page_id}")
        try:
            await page.set_viewport_size({"width": width, "height": height})
            measured = await page.evaluate(
                "() => ({width: window.innerWidth, height: window.innerHeight})"
            )
        except Exception as exc:
            raise BrowserError(f"browser viewport update failed: {exc}") from exc
        actual_width = width
        actual_height = height
        if isinstance(measured, dict):
            raw_width = measured.get("width")
            raw_height = measured.get("height")
            if isinstance(raw_width, (int, float)):
                actual_width = int(raw_width)
            if isinstance(raw_height, (int, float)):
                actual_height = int(raw_height)
        result = await self._summary(page_id, page)
        result.viewport = Dimensions(width=actual_width, height=actual_height)
        result.requested_viewport = Dimensions(width=width, height=height)
        return result

    async def set_page_label(self, page_id: str, label: str) -> PageSummary:
        self._require_agent_access(page_id)
        page = await self._page(page_id)
        normalized = label.strip()
        if len(normalized) > 120:
            raise BrowserError("browser page label must be at most 120 characters")
        async with self._policy_lock:
            if normalized:
                self._page_labels[page_id] = normalized
            else:
                self._page_labels.pop(page_id, None)
        return await self._summary(page_id, page)

    async def operator_set_page_label(
        self, owner_token: str, page_id: str, label: str
    ) -> PageSummary:
        self._require_operator(owner_token)
        page = await self._page(page_id)
        normalized = label.strip()
        if len(normalized) > 120:
            raise BrowserError("browser page label must be at most 120 characters")
        async with self._policy_lock:
            if normalized:
                self._page_labels[page_id] = normalized
            else:
                self._page_labels.pop(page_id, None)
        return await self._summary(page_id, page)

    async def operator_set_page_agent_access(
        self, owner_token: str, page_id: str, allowed: bool
    ) -> PageSummary:
        self._require_operator(owner_token)
        page = await self._page(page_id)
        async with self._policy_lock:
            if allowed:
                self._page_agent_access.pop(page_id, None)
            else:
                self._page_agent_access[page_id] = False
        return await self._summary(page_id, page)

    async def operator_set_agent_access(self, owner_token: str, allowed: bool) -> AgentAccessStatus:
        self._require_operator(owner_token)
        async with self._policy_lock:
            self._policy.agent_access_enabled = allowed
            await asyncio.to_thread(self._persist_policy)
        await self._notify_privileged_access()
        return AgentAccessStatus(
            agent_access_enabled=self._policy.agent_access_enabled,
            developer_access_effective=self.developer_access_effective,
        )

    async def operator_set_developer_access(
        self,
        owner_token: str,
        allowed: bool,
    ) -> DeveloperAccessReceipt:
        self._require_operator(owner_token)
        previous = self._policy.developer_access_enabled
        sync_result = DeveloperSyncResult(
            in_developer_mode=None,
            user_scripts_enabled=allowed,
            user_scripts_extension_count=0,
            extensions=[],
        )
        if allowed != previous:
            try:
                sync_result = await self._set_chromium_developer_state(allowed)
            except Exception:
                with contextlib.suppress(Exception):
                    await self._set_chromium_developer_state(previous)
                raise
        self._user_scripts_sync_error = ""
        async with self._policy_lock:
            self._policy.developer_access_enabled = allowed
            await asyncio.to_thread(self._persist_policy)
        await self._notify_privileged_access()
        return DeveloperAccessReceipt(
            developer_access_enabled=self._policy.developer_access_enabled,
            developer_access_effective=self.developer_access_effective,
            in_developer_mode=sync_result.in_developer_mode,
            user_scripts_enabled=sync_result.user_scripts_enabled,
            user_scripts_extension_count=sync_result.user_scripts_extension_count,
            extensions=sync_result.extensions,
        )

    async def operator_new_page(self, owner_token: str, url: str = "") -> PageSummary:
        return await create_operator_page(self, owner_token, url)

    async def operator_clean_browser(self, owner_token: str) -> CleanBrowserResult:
        return await clean_operator_browser(self, owner_token)

    async def _operator_page_items(self) -> list[PageSummary]:
        context = await self._ensure_started()
        items: list[PageSummary] = []
        for page in list(context.pages):
            if page.is_closed():
                continue
            page_id = self._register_page(page)
            items.append(await self._summary(page_id, page))
        return items

    async def operator_acquire(self) -> OperatorLease:
        await self._ensure_started()
        page_items = await self._operator_page_items()
        selected_page_id = page_items[0].page_id if page_items else ""
        owner_token = uuid.uuid4().hex
        async with self._operator_lock:
            self._operator_pages[owner_token] = selected_page_id
        return OperatorLease(owner_token=owner_token, selected_page_id=selected_page_id)

    async def operator_release(self, owner_token: str) -> None:
        async with self._operator_lock:
            self._operator_pages.pop(owner_token, None)

    async def operator_state(self, owner_token: str) -> OperatorState:
        self._require_operator(owner_token)
        page_items = await self._operator_page_items()
        valid_ids = {item.page_id for item in page_items if item.page_id}
        selected_page_id = self._operator_pages.get(owner_token, "")
        if selected_page_id not in valid_ids:
            selected_page_id = next(iter(valid_ids), "")
            async with self._operator_lock:
                if owner_token in self._operator_pages:
                    self._operator_pages[owner_token] = selected_page_id
        return OperatorState(
            control="shared",
            selected_page_id=selected_page_id,
            pages=page_items,
            page_count=len(page_items),
            operator_count=len(self._operator_pages),
            agent_access_enabled=self._policy.agent_access_enabled,
            developer_access_enabled=self._policy.developer_access_enabled,
            developer_access_effective=self.developer_access_effective,
            developer_backend="chrome-devtools-mcp",
            can_reopen_closed_tab=bool(self._closed_pages),
            capabilities=Capabilities(set_viewport=True, set_theme=True, remote_devtools=True),
            color_scheme=self._policy.color_scheme,
            viewport=Dimensions(width=self.viewport_width, height=self.viewport_height),
            screen=Dimensions(width=self.screen_width, height=self.screen_height),
        )

    async def operator_select_page(self, owner_token: str, page_id: str) -> None:
        self._require_operator(owner_token)
        await self._page(page_id)
        async with self._operator_lock:
            self._operator_pages[owner_token] = page_id

    async def operator_cdp_session(self, owner_token: str, page_id: str) -> tuple[Page, CDPSession]:
        self._require_operator(owner_token)
        context = await self._ensure_started()
        page = await self._page(page_id)
        return page, await context.new_cdp_session(page)

    async def operator_navigate(self, owner_token: str, page_id: str, url: str) -> PageSummary:
        self._require_operator(owner_token)
        page = await self._page(page_id)
        response = await page.goto(self._operator_url(url), wait_until="domcontentloaded")
        result = await self._summary(page_id, page)
        result.http_status = response.status if response is not None else None
        return result

    async def operator_clean_app(
        self,
        owner_token: str,
        page_id: str,
    ) -> PageSummary:
        self._require_operator(owner_token)
        context = await self._ensure_started()
        page = await self._page(page_id)
        parsed = urlsplit(page.url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise BrowserError("Clean App requires an http(s) application tab")
        origin = f"{parsed.scheme}://{parsed.netloc}"
        session = await context.new_cdp_session(page)
        deleted_cookies = 0
        try:
            cookie_payload = await session.send("Network.getCookies", {"urls": [page.url]})
            cookies = cookie_payload.get("cookies", [])
            if isinstance(cookies, list):
                for cookie in cookies:
                    if not isinstance(cookie, dict):
                        continue
                    name = cookie.get("name")
                    domain = cookie.get("domain")
                    path = cookie.get("path")
                    if not all(isinstance(value, str) for value in (name, domain, path)):
                        continue
                    await session.send(
                        "Network.deleteCookies",
                        {"name": name, "domain": domain, "path": path},
                    )
                    deleted_cookies += 1
            await session.send(
                "Storage.clearDataForOrigin",
                {"origin": origin, "storageTypes": "all"},
            )
        finally:
            await session.detach()
        await page.reload(wait_until="domcontentloaded")
        result = await self._summary(page_id, page)
        result.cleaned_app = True
        result.cleaned_origin = origin
        result.deleted_cookie_count = deleted_cookies
        return result

    async def operator_back(self, owner_token: str, page_id: str) -> PageSummary:
        self._require_operator(owner_token)
        page = await self._page(page_id)
        await page.go_back(wait_until="domcontentloaded")
        return await self._summary(page_id, page)

    async def operator_reload(self, owner_token: str, page_id: str) -> PageSummary:
        self._require_operator(owner_token)
        page = await self._page(page_id)
        await page.reload(wait_until="domcontentloaded")
        return await self._summary(page_id, page)

    async def operator_mouse(
        self,
        owner_token: str,
        page_id: str,
        *,
        event_type: str,
        x: float,
        y: float,
        button: str,
        click_count: int,
        delta_x: float,
        delta_y: float,
    ) -> None:
        self._require_operator(owner_token)
        page = await self._page(page_id)
        if event_type == "mouseMoved":
            await page.mouse.move(x, y)
            return
        if event_type == "mouseWheel":
            await page.mouse.move(x, y)
            await page.mouse.wheel(delta_x, delta_y)
            return
        if event_type not in {"mousePressed", "mouseReleased"}:
            raise BrowserError("unsupported mouse event")
        button_name: Literal["left", "middle", "right"] = "left"
        if button == "middle":
            button_name = "middle"
        elif button == "right":
            button_name = "right"
        await page.mouse.move(x, y)
        if event_type == "mousePressed":
            await page.mouse.down(button=button_name, click_count=max(1, click_count))
        else:
            await page.mouse.up(button=button_name, click_count=max(1, click_count))

    async def operator_key(self, owner_token: str, page_id: str, key: str) -> None:
        self._require_operator(owner_token)
        if not key.strip():
            raise BrowserError("key is required")
        page = await self._page(page_id)
        await page.keyboard.press(key)

    async def operator_text(self, owner_token: str, page_id: str, text: str) -> None:
        self._require_operator(owner_token)
        if len(text) > 10_000:
            raise BrowserError("operator text input is too large")
        page = await self._page(page_id)
        await page.keyboard.insert_text(text)
