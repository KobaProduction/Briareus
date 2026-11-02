"""Compatibility API for the bounded Web runtime implementation."""

import json as json

from modules.web.domain.browser_policy import BrowserPolicy as BrowserPolicy
from web_runtime.infrastructure.browser_policy import encode_browser_policy as encode_browser_policy
from web_runtime.infrastructure.browser_policy import (
    restore_browser_policy as restore_browser_policy,
)
