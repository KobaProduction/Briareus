"""Compatibility API for the bounded Web runtime implementation."""

from dataclasses import dataclass as dataclass
from pathlib import Path as Path

from web_runtime.browser_profile import (
    DEFAULT_BROWSER_DESKTOP_PROFILE as DEFAULT_BROWSER_DESKTOP_PROFILE,
)
from web_runtime.browser_profile import BrowserDesktopProfile as BrowserDesktopProfile
from web_runtime.browser_profile import resolve_chromium_gpu_args as resolve_chromium_gpu_args
