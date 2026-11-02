"""Read the existing shared launch profile and persisted extension registry."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from common.browser_extensions import BrowserExtensionRegistry
from common.browser_profile import BrowserDesktopProfile, resolve_chromium_gpu_args
from common.settings import BrowserSettings, FileSettings


@dataclass(frozen=True, slots=True)
class BrowserLaunchConfig:
    executable: str
    profile: Path
    desktop: BrowserDesktopProfile
    timezone: str
    chromium_args: tuple[str, ...]
    extension_paths: tuple[str, ...]
    force_dark_mode: bool


class BrowserLaunchSource:
    def __init__(self, settings: BrowserSettings, desktop: BrowserDesktopProfile) -> None:
        self.settings = settings
        self.desktop = desktop

    def current(self) -> BrowserLaunchConfig:
        profile = self.settings.profile_dir
        extensions = BrowserExtensionRegistry(
            profile.parent / "dev-extensions.json", FileSettings().workspace_root
        )
        dark = True
        try:
            policy: object = json.loads((profile / "koba-browser-policy.json").read_text())
        except (OSError, json.JSONDecodeError):
            policy = None
        if isinstance(policy, dict):
            dark = policy.get("color_scheme", "dark") == "dark"
        return BrowserLaunchConfig(
            self.settings.executable_path,
            profile,
            self.desktop,
            self.settings.timezone,
            (*self.desktop.chromium_args, *resolve_chromium_gpu_args()),
            extensions.load_paths(),
            dark,
        )
