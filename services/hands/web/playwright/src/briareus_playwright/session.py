from __future__ import annotations

from dataclasses import dataclass

from briareus_workspace.settings import FileSettings
from briareus_workspace.workspace_store import WorkspaceFileStore

from .browser import BrowserManager
from .browser_launch import BrowserLaunchSource
from .browser_profile import DEFAULT_BROWSER_DESKTOP_PROFILE, resolve_chromium_gpu_args
from .settings import BrowserSettings


@dataclass(frozen=True)
class BrowserSession:
    settings: BrowserSettings
    browser: BrowserManager


def create_browser_session() -> BrowserSession:
    settings = BrowserSettings()
    profile = DEFAULT_BROWSER_DESKTOP_PROFILE
    workspace = WorkspaceFileStore(FileSettings().workspace_root)
    launch = BrowserLaunchSource(settings, profile, workspace.root)
    browser = BrowserManager(
        prepare_launch=launch.write_manifest,
        workspace=workspace,
        cdp_url=settings.cdp_url,
        control_url=settings.control_url,
        control_token=settings.control_token,
        profile_dir=settings.profile_dir,
        executable_path=settings.executable_path,
        headless=profile.headless,
        timeout_ms=settings.timeout_ms,
        viewport_width=profile.viewport_width,
        viewport_height=profile.viewport_height,
        screen_width=profile.screen_width,
        screen_height=profile.screen_height,
        locale=profile.locale,
        accept_language=profile.accept_language,
        display=profile.display,
        color_depth=profile.color_depth,
        xvfb_enabled=profile.xvfb_enabled,
        timezone=settings.timezone,
        posix_locale=profile.posix_locale,
        chromium_args=(*profile.chromium_args, *resolve_chromium_gpu_args()),
        max_snapshot_text_chars=settings.max_snapshot_text_chars,
        max_snapshot_elements=settings.max_snapshot_elements,
    )
    return BrowserSession(settings=settings, browser=browser)
