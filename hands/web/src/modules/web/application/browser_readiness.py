"""Compatibility API for the bounded Web runtime implementation."""

from dataclasses import dataclass as dataclass
from typing import Protocol as Protocol

from modules.web.domain.browser_readiness import BrowserReadiness as BrowserReadiness
from web_runtime.application.browser_readiness import BrowserReadinessProbe as BrowserReadinessProbe
from web_runtime.application.browser_readiness import (
    ObserveBrowserReadiness as ObserveBrowserReadiness,
)
