"""Web-owned translation from browser policy to the external image's argv manifest."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from briareus_web.browser_extensions import BrowserExtensionRegistry
from briareus_web.browser_profile import BrowserDesktopProfile, resolve_chromium_gpu_args
from briareus_web.settings import BrowserSettings


@dataclass(frozen=True, slots=True)
class BrowserLaunchConfig:
    profile: Path
    desktop: BrowserDesktopProfile
    timezone: str
    chromium_args: tuple[str, ...]
    extension_paths: tuple[str, ...]
    force_dark_mode: bool

    def arguments(self) -> tuple[str, ...]:
        desktop = self.desktop
        flags = [
            f"--window-size={desktop.viewport_width},{desktop.viewport_height}",
            *self.chromium_args,
        ]
        if self.force_dark_mode:
            flags.append("--force-dark-mode")
        if self.extension_paths:
            flags.append("--load-extension=" + ",".join(self.extension_paths))
        if desktop.locale:
            flags.append(f"--lang={desktop.locale}")
        if desktop.accept_language:
            flags.append(f"--accept-lang={desktop.accept_language}")
        if desktop.headless:
            flags.append("--headless=new")
        return tuple(flags)


class BrowserLaunchSource:
    def __init__(
        self, settings: BrowserSettings, desktop: BrowserDesktopProfile, workspace_root: Path
    ) -> None:
        self.settings = settings
        self.desktop = desktop
        self.workspace_root = workspace_root

    def current(self) -> BrowserLaunchConfig:
        profile = self.settings.profile_dir
        extensions = BrowserExtensionRegistry(
            profile.parent / "dev-extensions.json", self.workspace_root
        )
        dark = True
        try:
            policy: object = json.loads(
                (profile / "koba-browser-policy.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            policy = None
        if isinstance(policy, dict):
            dark = policy.get("color_scheme", "dark") == "dark"
        return BrowserLaunchConfig(
            profile,
            self.desktop,
            self.settings.timezone,
            (*self.desktop.chromium_args, *resolve_chromium_gpu_args()),
            extensions.load_paths(),
            dark,
        )

    def write_manifest(self) -> Path:
        config = self.current()
        destination = config.profile.parent / "launch-arguments.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(json.dumps(config.arguments()), encoding="utf-8")
        temporary.replace(destination)
        return destination
