from __future__ import annotations

import asyncio
import contextlib
import json
import shutil
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, CDPSession, Locator, Page, Playwright

import httpx
from briareus_json_values import JsonObject, JsonValue
from briareus_workspace.workspace_store import WorkspaceFileStore

from briareus_web.browser_extensions import BrowserExtensionRegistry

from .browser_control import BrowserControlClient
from .developer_sync import DEVELOPER_SYNC_SCRIPT, DeveloperSyncResult
from .downloads import BrowserDownloadError, BrowserDownloadStore

_PAGE_TITLE_TIMEOUT_SECONDS = 2.0


class BrowserError(RuntimeError):
    """Browser operation failed."""


class BrowserManager:
    def __init__(
        self,
        *,
        workspace: WorkspaceFileStore,
        cdp_url: str,
        control_url: str,
        control_token: str,
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
        prepare_launch: Callable[[], object] | None = None,
    ) -> None:
        self.cdp_url = cdp_url.rstrip("/")
        self._control = BrowserControlClient(
            control_url, control_token, prepare_launch=prepare_launch
        )
        self.workspace = workspace
        self._downloads = BrowserDownloadStore(workspace)
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
        self._manually_stopped = False
        self._context: BrowserContext | None = None
        self._pages: dict[str, Page] = {}
        self._page_ids: dict[int, str] = {}
        self._start_lock = asyncio.Lock()
        self._reset_lock = asyncio.Lock()
        self._operator_lock = asyncio.Lock()
        self._operator_pages: dict[str, str] = {}
        self._policy_lock = asyncio.Lock()
        self._policy_path = self.profile_dir / "koba-browser-policy.json"
        self._agent_access_enabled = True
        self._developer_access_enabled = False
        self._color_scheme: Literal["system", "light", "dark"] = "dark"
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
        self._blocked_target_ids: set[str] = set()
        self._closed_pages: list[dict[str, object]] = []
        self._load_policy()

    def _load_policy(self) -> None:
        try:
            payload = json.loads(self._policy_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        if isinstance(payload.get("agent_access_enabled"), bool):
            self._agent_access_enabled = payload["agent_access_enabled"]
        if isinstance(payload.get("developer_access_enabled"), bool):
            self._developer_access_enabled = payload["developer_access_enabled"]
        targets = payload.get("blocked_target_ids", [])
        if isinstance(targets, list):
            self._blocked_target_ids = {item for item in targets if isinstance(item, str)}
        color_scheme = payload.get("color_scheme")
        if color_scheme in {"system", "light", "dark"}:
            self._color_scheme = cast(Literal["system", "light", "dark"], color_scheme)

    def _persist_policy(self) -> None:
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        temporary = self._policy_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "agent_access_enabled": self._agent_access_enabled,
                    "developer_access_enabled": self._developer_access_enabled,
                    "color_scheme": self._color_scheme,
                    "blocked_target_ids": sorted(self._blocked_target_ids),
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        temporary.replace(self._policy_path)

    @property
    def developer_access_enabled(self) -> bool:
        return self._developer_access_enabled

    @property
    def developer_access_effective(self) -> bool:
        return self._agent_access_enabled and self._developer_access_enabled

    def require_developer_access(self) -> None:
        if not self._agent_access_enabled:
            raise BrowserError("browser agent access is disabled by operator")
        if not self._developer_access_enabled:
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
        if not self._agent_access_enabled:
            return False
        return not (page_id and not self._page_agent_access.get(page_id, True))

    def _require_agent_access(self, page_id: str = "") -> None:
        if not self._agent_access_enabled:
            raise BrowserError("browser agent access is disabled by operator")
        if page_id and not self._page_agent_access.get(page_id, True):
            raise BrowserError(f"browser page is locked by operator: {page_id}")

    async def _cdp_reachable(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=2) as client:
                response = await client.get(f"{self.cdp_url}/json/version")
                return response.status_code == 200
        except httpx.RequestError:
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

    async def _start_locked(self) -> None:
        if self._context is not None:
            return
        state = await self._control.command("state")
        if state.manually_stopped:
            self._manually_stopped = True
            raise BrowserError("Chromium was explicitly stopped; call browser_restart")
        from playwright.async_api import async_playwright

        playwright = await async_playwright().start()
        try:
            browser = await playwright.chromium.connect_over_cdp(self.cdp_url, timeout=20_000)
            if not browser.contexts:
                raise BrowserError("Chromium exposed no persistent context")
            context = browser.contexts[0]
        except Exception:
            await playwright.stop()
            raise
        context.set_default_timeout(self.timeout_ms)
        context.set_default_navigation_timeout(self.timeout_ms)
        self._playwright = playwright
        self._browser = browser
        self._context = context
        for page in context.pages:
            page_id = self._register_page(page)
            target_id = await self._target_id(page)
            if target_id in self._blocked_target_ids:
                self._page_agent_access[page_id] = False
            await self._apply_color_scheme(page)
        try:
            await self._set_chromium_developer_state(
                self._developer_access_enabled, context=context
            )
        except BrowserError as exc:
            self._user_scripts_sync_error = str(exc)
        else:
            self._user_scripts_sync_error = ""
        context.on("page", self._on_context_page)

    async def _ensure_started(self) -> BrowserContext:
        if self._manually_stopped:
            raise BrowserError("browser was hard-stopped; call browser_restart to start it")
        if self._context is not None and await self._context_usable():
            return self._context
        async with self._start_lock:
            if self._context is not None and await self._context_usable():
                return self._context
            await self._stop_runtime(stop_display=False)
            await self._start_locked()
            if self._context is None:
                raise BrowserError("browser context is unavailable")
            return self._context

    async def _stop_runtime(self, *, stop_display: bool) -> None:
        # Web disconnects its CDP transport. It never closes persistent remote pages.
        await self._downloads.disconnect()
        playwright = self._playwright
        self._context = None
        self._browser = None
        self._playwright = None
        if playwright is not None:
            with contextlib.suppress(Exception):
                await playwright.stop()
        self._pages.clear()
        self._page_ids.clear()
        self._page_agent_access.clear()
        if stop_display:
            await self._control.command("stop")

    async def restart(self) -> JsonObject:
        """Explicitly restart the independent Chromium owner, preserving its profile."""
        async with self._reset_lock:
            await self._notify_restart()
            await self._stop_runtime(stop_display=False)
            await self._control.command("restart")
            self._manually_stopped = False
            self._developer_backend_connected = False
            async with self._start_lock:
                await self._start_locked()
        return await self.status()

    async def hard_stop(self) -> JsonObject:
        """Explicitly stop Chromium through its private process owner."""
        async with self._reset_lock:
            self._manually_stopped = True
            await self._notify_restart()
            await self._stop_runtime(stop_display=True)
            self._developer_backend_connected = False
        return {"stopped": True, "profile_preserved": True}

    async def recover_if_broken(self) -> bool:
        if self._manually_stopped or await self._context_usable():
            return False
        await self._ensure_started()
        return True

    def record_dev_extension(self, extension_id: str, path: str) -> None:
        self._extension_registry.record(extension_id, path)

    def forget_dev_extension(self, extension_id: str) -> None:
        self._extension_registry.remove(extension_id)

    def dev_extensions(self) -> list[JsonValue]:
        return [{"id": item.id, "path": item.path} for item in self._extension_registry.items()]

    async def _set_chromium_developer_state(
        self,
        enabled: bool,
        *,
        extension_ids: list[str] | None = None,
        update_profile_mode: bool = True,
        context: BrowserContext | None = None,
    ) -> JsonObject:
        context = context or await self._ensure_started()
        page = await context.new_page()
        page_id = self._register_page(page)
        try:
            await page.goto("chrome://extensions/", wait_until="domcontentloaded")
            requested_ids = (
                None if extension_ids is None else [value for value in extension_ids if value]
            )
            result = await page.evaluate(
                DEVELOPER_SYNC_SCRIPT,
                {
                    "enabled": enabled,
                    "extensionIds": requested_ids,
                    "updateProfileMode": update_profile_mode,
                },
            )
            payload = DeveloperSyncResult.model_validate(result)
        except Exception as exc:
            raise BrowserError(f"Chromium developer-mode synchronization failed: {exc}") from exc
        finally:
            with contextlib.suppress(Exception):
                await page.close()
            self._forget_page(page_id)

        self._update_managed_user_scripts(set(payload.eligibleExtensionIds), extension_ids)
        details = payload.failure_details()
        if details:
            raise BrowserError(f"Chromium userScripts access synchronization failed: {details}")
        return payload.response(enabled)

    def _update_managed_user_scripts(
        self, eligible_ids: set[str], requested_ids: list[str] | None
    ) -> None:
        if requested_ids is None:
            self._managed_user_scripts_extension_ids = eligible_ids
            return
        for extension_id in requested_ids:
            if extension_id in eligible_ids:
                self._managed_user_scripts_extension_ids.add(extension_id)
            else:
                self._managed_user_scripts_extension_ids.discard(extension_id)

    async def sync_dev_extension_user_scripts(self, extension_id: str) -> JsonObject:
        result = await self._set_chromium_developer_state(
            self._developer_access_enabled,
            extension_ids=[extension_id],
            update_profile_mode=False,
        )
        return {
            "extension_id": extension_id,
            "user_scripts_managed": extension_id in self._managed_user_scripts_extension_ids,
            "user_scripts_enabled": (
                self._developer_access_enabled
                if extension_id in self._managed_user_scripts_extension_ids
                else False
            ),
            **result,
        }

    async def _apply_color_scheme(self, page: Page) -> None:
        scheme = None if self._color_scheme == "system" else self._color_scheme
        try:
            await page.emulate_media(color_scheme=scheme)
        except Exception as exc:
            raise BrowserError(f"browser color scheme update failed: {exc}") from exc

    def _on_context_page(self, page: Page) -> None:
        self._register_page(page)
        task = asyncio.create_task(
            self._apply_color_scheme(page), name="browser-apply-color-scheme"
        )
        task.add_done_callback(lambda item: item.exception() if not item.cancelled() else None)

    async def set_color_scheme(self, color_scheme: str) -> JsonObject:
        normalized = color_scheme.strip().casefold()
        if normalized not in {"system", "light", "dark"}:
            raise BrowserError("browser color scheme must be system, light, or dark")
        self._color_scheme = cast(Literal["system", "light", "dark"], normalized)
        await asyncio.to_thread(self._persist_policy)
        context = await self._ensure_started()
        updated = 0
        for page in list(context.pages):
            if page.is_closed():
                continue
            await self._apply_color_scheme(page)
            updated += 1
        result = await self.status()
        result["updated_pages"] = updated
        result["native_ui_restart_required"] = True
        return result

    async def debug_target(self, page_id: str) -> JsonObject:
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
        return {
            "page_id": page_id,
            "target_id": target_id,
            "title": await page.title(),
            "url": page.url,
        }

    async def _target_id(self, page: Page) -> str:
        context = self._context
        if context is None:
            raise BrowserError("browser context is unavailable")
        session = await context.new_cdp_session(page)
        try:
            result = await session.send("Target.getTargetInfo")
            return str(result["targetInfo"]["targetId"])
        finally:
            await session.detach()

    def _register_page(self, page: Page) -> str:
        key = id(page)
        existing = self._page_ids.get(key)
        if existing:
            return existing
        page_id = f"page-{uuid.uuid4().hex[:10]}"
        self._pages[page_id] = page
        self._page_ids[key] = page_id
        page.on("download", self._downloads.schedule)
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
        if value in {
            "chrome://extensions",
            "chrome://extensions/",
            "chrome://settings",
            "chrome://settings/",
            "chrome://version",
            "chrome://version/",
        }:
            return value
        return cls._url(value)

    @staticmethod
    async def _page_title(page: Page) -> str:
        try:
            return await asyncio.wait_for(page.title(), timeout=_PAGE_TITLE_TIMEOUT_SECONDS)
        except Exception:
            # One blocked renderer or navigation race must not hide every other tab.
            return ""

    async def _summary(self, page_id: str, page: Page) -> JsonObject:
        return {
            "page_id": page_id,
            "label": self._page_labels.get(page_id, ""),
            "page_agent_access": self._page_agent_access.get(page_id, True),
            "agent_access": self._agent_access_allowed(page_id),
            "url": page.url,
            "title": await self._page_title(page),
        }

    async def _agent_summary(self, page_id: str, page: Page) -> JsonObject:
        if self._agent_access_allowed(page_id):
            return await self._summary(page_id, page)
        return {
            "page_id": page_id,
            "label": self._page_labels.get(page_id, ""),
            "page_agent_access": self._page_agent_access.get(page_id, True),
            "agent_access": False,
            "locked": True,
            "url": "",
            "title": "",
        }

    async def diagnostics(self) -> JsonObject:
        state = await self._control.command("state")
        return {
            "cdp_url": self.cdp_url,
            "process_running": state.running,
            "manually_stopped": state.manually_stopped,
            "profile_dir": str(self.profile_dir),
        }

    async def _observed_runtime(self) -> JsonObject:
        context = self._context
        if context is None or not await self._context_usable():
            return {}
        pages = [page for page in context.pages if not page.is_closed()]
        if not pages:
            return {}
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
            return {}
        return cast(JsonObject, observed) if isinstance(observed, dict) else {}

    async def status(self) -> JsonObject:
        if not self._manually_stopped and self._context is None:
            await self._ensure_started()

        remote_state = await self._control.command("state")
        process_running = remote_state.running
        self._manually_stopped = remote_state.manually_stopped
        cdp_reachable = process_running and await self._cdp_reachable()
        context_usable = cdp_reachable and await self._context_usable()
        pages: list[JsonValue] = []
        if context_usable and self._context is not None:
            active_pages = [page for page in list(self._context.pages) if not page.is_closed()]
            pages.extend(await asyncio.gather(*(
                self._agent_summary(self._register_page(page), page) for page in active_pages
            )))
        observed = await self._observed_runtime() if context_usable else {}
        if not cdp_reachable:
            self._developer_backend_connected = False
        running = bool(process_running and cdp_reachable and context_usable)
        return {
            "running": running,
            "process_running": process_running,
            "manually_stopped": self._manually_stopped,
            "cdp_reachable": cdp_reachable,
            "context_usable": context_usable,
            "agent_access_enabled": self._agent_access_enabled,
            "developer_access_enabled": self._developer_access_enabled,
            "developer_access_effective": self.developer_access_effective,
            "developer_backend": "chrome-devtools-mcp",
            "developer_backend_connected": self._developer_backend_connected,
            "headless": self.headless,
            "browser": "chromium",
            "capabilities": {
                "set_viewport": True,
                "set_theme": True,
                "remote_devtools": True,
            },
            "color_scheme": self._color_scheme,
            "locale": self.locale,
            "accept_language": self.accept_language,
            "display": "" if self.headless else self.display,
            "xvfb_enabled": self.xvfb_enabled,
            "timezone": self.timezone,
            "posix_locale": self.posix_locale,
            "chromium_args": list(self.chromium_args),
            "executable_path": self.executable_path,
            "profile_dir": str(self.profile_dir),
            "dev_extensions": self.dev_extensions(),
            "managed_user_scripts_extension_count": len(self._managed_user_scripts_extension_ids),
            "user_scripts_follow_developer_access": True,
            "user_scripts_sync_error": self._user_scripts_sync_error,
            "observed": observed,
            "page_count": len(pages),
            "pages": pages,
        }

    async def pages(self) -> JsonObject:
        status = await self.status()
        raw_pages = status.get("pages")
        pages = raw_pages if isinstance(raw_pages, list) else []
        return {"count": len(pages), "pages": pages}

    async def open(self, url: str, page_id: str = "") -> JsonObject:
        context = await self._ensure_started()
        target_url = self._url(url)
        self._require_agent_access(page_id)
        if page_id:
            page = await self._page(page_id)
        else:
            page = await context.new_page()
            page_id = self._register_page(page)
        response = await page.goto(target_url, wait_until="domcontentloaded")
        result = await self._summary(page_id, page)
        result["http_status"] = response.status if response is not None else None
        return result

    async def snapshot(
        self,
        page_id: str,
        *,
        max_text_chars: int | None = None,
        max_elements: int | None = None,
    ) -> JsonObject:
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
        elements = cast(list[JsonValue], raw_elements)
        summary = await self._summary(page_id, page)
        summary.update(
            {
                "text": text,
                "text_truncated": text_truncated,
                "elements": elements,
                "element_count": len(elements),
            }
        )
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

    async def click(self, page_id: str, ref: str) -> JsonObject:
        page, locator = await self._locator(page_id, ref)
        await locator.click()
        await page.wait_for_timeout(150)
        return await self._summary(page_id, page)

    async def fill(self, page_id: str, ref: str, value: str, *, press_enter: bool) -> JsonObject:
        page, locator = await self._locator(page_id, ref)
        await locator.fill(value)
        if press_enter:
            await locator.press("Enter")
            await page.wait_for_timeout(150)
        return await self._summary(page_id, page)

    async def press(self, page_id: str, ref: str, key: str) -> JsonObject:
        page, locator = await self._locator(page_id, ref)
        await locator.press(key)
        await page.wait_for_timeout(100)
        return await self._summary(page_id, page)

    async def select_option(self, page_id: str, ref: str, value: str) -> JsonObject:
        page, locator = await self._locator(page_id, ref)
        selected = await locator.select_option(value=value)
        result = await self._summary(page_id, page)
        result["selected"] = cast(list[JsonValue], selected)
        return result

    async def upload(self, page_id: str, ref: str, workspace_path: str) -> JsonObject:
        page, locator = await self._locator(page_id, ref)
        source = self.workspace.path_for(workspace_path)
        if not source.is_file():
            raise BrowserError(f"upload path is not a file: {workspace_path}")
        await locator.set_input_files(str(source))
        result = await self._summary(page_id, page)
        result["workspace_path"] = self.workspace.relative(source)
        return result

    async def download(
        self,
        page_id: str,
        ref: str,
        workspace_path: str = "",
        *,
        overwrite: bool = False,
    ) -> JsonObject:
        page, locator = await self._locator(page_id, ref)
        target = self.workspace.target_path(workspace_path) if workspace_path.strip() else None
        if target is not None and target.is_dir():
            raise BrowserError(f"destination is a directory: {workspace_path}")
        if target is not None and target.exists() and not overwrite:
            raise BrowserError(f"destination already exists: {workspace_path}")
        async with page.expect_download() as download_info:
            await locator.click()
        download = await download_info.value
        try:
            saved = await self._downloads.saved(download)
        except BrowserDownloadError as error:
            raise BrowserError(str(error)) from error
        path = self.workspace.relative(saved)
        if target is not None and target != saved:
            result = self.workspace.move(path, self.workspace.relative(target), overwrite=overwrite)
        else:
            result = self.workspace.info(path)
        result["suggested_filename"] = download.suggested_filename
        return result

    async def screenshot(
        self,
        page_id: str,
        workspace_path: str,
        *,
        full_page: bool,
        overwrite: bool,
    ) -> JsonObject:
        self._require_agent_access(page_id)
        page = await self._page(page_id)
        target = self.workspace.target_path(workspace_path)
        if target.exists() and not overwrite:
            raise BrowserError(f"destination already exists: {workspace_path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(target), full_page=full_page)
        return self.workspace.info(self.workspace.relative(target))

    async def wait(
        self,
        page_id: str,
        *,
        state: str,
        timeout_seconds: float,
    ) -> JsonObject:
        self._require_agent_access(page_id)
        page = await self._page(page_id)
        normalized = state.strip().casefold()
        if normalized not in {"load", "domcontentloaded", "networkidle"}:
            raise BrowserError("wait state must be load, domcontentloaded, or networkidle")
        if not 0 < timeout_seconds <= 120:
            raise BrowserError("timeout_seconds must be between 0 and 120")
        load_state = cast(
            Literal["load", "domcontentloaded", "networkidle"],
            normalized,
        )
        await page.wait_for_load_state(load_state, timeout=timeout_seconds * 1000)
        return await self._summary(page_id, page)

    async def back(self, page_id: str) -> JsonObject:
        self._require_agent_access(page_id)
        page = await self._page(page_id)
        await page.go_back(wait_until="domcontentloaded")
        return await self._summary(page_id, page)

    async def reload(self, page_id: str) -> JsonObject:
        self._require_agent_access(page_id)
        page = await self._page(page_id)
        response = await page.reload(wait_until="domcontentloaded")
        result = await self._summary(page_id, page)
        result["http_status"] = response.status if response is not None else None
        return result

    async def close_page(self, page_id: str) -> JsonObject:
        self._require_agent_access(page_id)
        page = await self._page(page_id)
        await page.close()
        self._forget_page(page_id)
        return {"page_id": page_id, "closed": True}

    async def set_viewport(self, page_id: str, width: int, height: int) -> JsonObject:
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
        result["viewport"] = {"width": actual_width, "height": actual_height}
        result["requested_viewport"] = {"width": width, "height": height}
        return result

    async def set_page_label(self, page_id: str, label: str) -> JsonObject:
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
    ) -> JsonObject:
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
    ) -> JsonObject:
        self._require_operator(owner_token)
        page = await self._page(page_id)
        target_id = await self._target_id(page)
        async with self._policy_lock:
            if allowed:
                self._page_agent_access.pop(page_id, None)
                self._blocked_target_ids.discard(target_id)
            else:
                self._page_agent_access[page_id] = False
                self._blocked_target_ids.add(target_id)
            await asyncio.to_thread(self._persist_policy)
        return await self._summary(page_id, page)

    async def operator_set_agent_access(self, owner_token: str, allowed: bool) -> JsonObject:
        self._require_operator(owner_token)
        async with self._policy_lock:
            self._agent_access_enabled = allowed
            await asyncio.to_thread(self._persist_policy)
        await self._notify_privileged_access()
        return {
            "agent_access_enabled": self._agent_access_enabled,
            "developer_access_effective": self.developer_access_effective,
        }

    async def operator_set_developer_access(self, owner_token: str, allowed: bool) -> JsonObject:
        self._require_operator(owner_token)
        previous = self._developer_access_enabled
        sync_result: JsonObject = {
            "in_developer_mode": None,
            "user_scripts_enabled": allowed,
            "user_scripts_extension_count": 0,
            "extensions": [],
        }
        if allowed != previous:
            try:
                sync_result = await self._set_chromium_developer_state(allowed)
            except Exception:
                with contextlib.suppress(Exception):
                    await self._set_chromium_developer_state(previous)
                raise
        self._user_scripts_sync_error = ""
        async with self._policy_lock:
            self._developer_access_enabled = allowed
            await asyncio.to_thread(self._persist_policy)
        await self._notify_privileged_access()
        return {
            "developer_access_enabled": self._developer_access_enabled,
            "developer_access_effective": self.developer_access_effective,
            **sync_result,
        }

    async def _operator_page_items(self) -> list[JsonValue]:
        context = await self._ensure_started()
        items: list[JsonValue] = []
        for page in list(context.pages):
            if page.is_closed():
                continue
            page_id = self._register_page(page)
            items.append(await self._summary(page_id, page))
        return items

    async def operator_acquire(self) -> JsonObject:
        await self._ensure_started()
        page_items = await self._operator_page_items()
        selected_page_id = (
            str(page_items[0].get("page_id") or "")
            if page_items and isinstance(page_items[0], dict)
            else ""
        )
        owner_token = uuid.uuid4().hex
        async with self._operator_lock:
            self._operator_pages[owner_token] = selected_page_id
        return {
            "owner_token": owner_token,
            "selected_page_id": selected_page_id,
        }

    async def operator_release(self, owner_token: str) -> None:
        async with self._operator_lock:
            self._operator_pages.pop(owner_token, None)

    async def operator_state(self, owner_token: str) -> JsonObject:
        self._require_operator(owner_token)
        page_items = await self._operator_page_items()
        valid_ids = {
            str(item.get("page_id"))
            for item in page_items
            if isinstance(item, dict) and item.get("page_id")
        }
        selected_page_id = self._operator_pages.get(owner_token, "")
        if selected_page_id not in valid_ids:
            selected_page_id = next(iter(valid_ids), "")
            async with self._operator_lock:
                if owner_token in self._operator_pages:
                    self._operator_pages[owner_token] = selected_page_id
        return {
            "control": "shared",
            "selected_page_id": selected_page_id,
            "pages": page_items,
            "page_count": len(page_items),
            "operator_count": len(self._operator_pages),
            "agent_access_enabled": self._agent_access_enabled,
            "developer_access_enabled": self._developer_access_enabled,
            "developer_access_effective": self.developer_access_effective,
            "developer_backend": "chrome-devtools-mcp",
            "can_reopen_closed_tab": bool(self._closed_pages),
            "capabilities": {
                "set_viewport": True,
                "set_theme": True,
                "remote_devtools": True,
            },
            "color_scheme": self._color_scheme,
            "viewport": {"width": self.viewport_width, "height": self.viewport_height},
            "screen": {"width": self.screen_width, "height": self.screen_height},
        }

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

    async def operator_new_page(self, owner_token: str, url: str = "") -> JsonObject:
        self._require_operator(owner_token)
        context = await self._ensure_started()
        page = await context.new_page()
        page_id = self._register_page(page)
        if url.strip():
            await page.goto(self._operator_url(url), wait_until="domcontentloaded")
        async with self._operator_lock:
            self._operator_pages[owner_token] = page_id
        return await self._summary(page_id, page)

    async def operator_navigate(self, owner_token: str, page_id: str, url: str) -> JsonObject:
        self._require_operator(owner_token)
        page = await self._page(page_id)
        response = await page.goto(self._operator_url(url), wait_until="domcontentloaded")
        result = await self._summary(page_id, page)
        result["http_status"] = response.status if response is not None else None
        return result

    async def operator_clean_app(
        self,
        owner_token: str,
        page_id: str,
    ) -> JsonObject:
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
        result["cleaned_app"] = True
        result["cleaned_origin"] = origin
        result["deleted_cookie_count"] = deleted_cookies
        return result

    async def operator_clean_browser(self, owner_token: str) -> JsonObject:
        self._require_operator(owner_token)
        async with self._reset_lock:
            # Block agents before destroying the credential-bearing profile.
            async with self._policy_lock:
                self._agent_access_enabled = False
                self._developer_access_enabled = False
            await self._notify_privileged_access()

            await self._notify_restart()
            self._developer_backend_connected = False
            await self._stop_runtime(stop_display=True)
            self._extension_registry.clear()
            await asyncio.to_thread(shutil.rmtree, self.profile_dir, True)
            state_root = self.profile_dir.parent
            for name in ("cache", "config", "crash"):
                await asyncio.to_thread(shutil.rmtree, state_root / name, True)
            self.profile_dir.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(self._persist_policy)

            await self._control.command("start")
            self._manually_stopped = False
            async with self._start_lock:
                await self._start_locked()
            context = self._context
            if context is None:
                raise BrowserError("browser failed to restart after clean")
            page_items: list[JsonValue] = []
            for page in list(context.pages):
                if page.is_closed():
                    continue
                page_id = self._register_page(page)
                page_items.append(await self._summary(page_id, page))
            if not page_items:
                page = await context.new_page()
                page_id = self._register_page(page)
                page_items = [await self._summary(page_id, page)]
            first_page = page_items[0] if page_items else None
            selected_page_id = (
                str(first_page.get("page_id") or "") if isinstance(first_page, dict) else ""
            )
            async with self._operator_lock:
                for token in list(self._operator_pages):
                    self._operator_pages[token] = selected_page_id
            return {
                "cleaned": True,
                "agent_access_enabled": False,
                "developer_access_enabled": False,
                "developer_access_effective": False,
                "selected_page_id": selected_page_id,
                "page_count": len(page_items),
            }

    async def operator_back(self, owner_token: str, page_id: str) -> JsonObject:
        self._require_operator(owner_token)
        page = await self._page(page_id)
        await page.go_back(wait_until="domcontentloaded")
        return await self._summary(page_id, page)

    async def operator_reload(self, owner_token: str, page_id: str) -> JsonObject:
        self._require_operator(owner_token)
        page = await self._page(page_id)
        await page.reload(wait_until="domcontentloaded")
        return await self._summary(page_id, page)

    async def operator_reopen_closed_page(self, owner_token: str) -> JsonObject:
        self._require_operator(owner_token)
        if not self._closed_pages:
            raise BrowserError("no recently closed browser tab")
        item = self._closed_pages.pop()
        context = await self._ensure_started()
        page = await context.new_page()
        page_id = self._register_page(page)
        url = str(item.get("url") or "about:blank")
        if url != "about:blank":
            await page.goto(self._operator_url(url), wait_until="domcontentloaded")
        label = str(item.get("label") or "")
        if label:
            self._page_labels[page_id] = label
        if item.get("page_agent_access") is False:
            self._page_agent_access[page_id] = False
        async with self._operator_lock:
            self._operator_pages[owner_token] = page_id
        result = await self._summary(page_id, page)
        result["reopened"] = True
        return result

    async def operator_close_page(self, owner_token: str, page_id: str) -> JsonObject:
        self._require_operator(owner_token)
        page = await self._page(page_id)
        summary = await self._summary(page_id, page)
        url = str(summary.get("url") or "")
        if not url.startswith("devtools://"):
            self._closed_pages.append(
                {
                    "url": url or "about:blank",
                    "label": summary.get("label") or "",
                    "page_agent_access": summary.get("page_agent_access") is not False,
                }
            )
            del self._closed_pages[:-20]
        await page.close()
        self._forget_page(page_id)
        async with self._operator_lock:
            if self._operator_pages.get(owner_token) == page_id:
                self._operator_pages[owner_token] = ""
        return {"page_id": page_id, "closed": True}

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
        button_name = cast(
            Literal["left", "middle", "right"],
            button if button in {"left", "middle", "right"} else "left",
        )
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
