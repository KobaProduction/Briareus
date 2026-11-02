"""Only a genuinely pristine, non-developer profile can use Chrome defaults."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from modules.web.browser import BrowserManager
from web_runtime.browser_extensions import BrowserExtensionRegistry
from web_runtime.domain.browser_policy import BrowserPolicy


class DeveloperStartupPolicyTests(unittest.TestCase):
    def test_existing_state_and_requested_extensions_keep_policy_sync(self) -> None:
        with TemporaryDirectory() as directory:
            browser = object.__new__(BrowserManager)
            browser.profile_dir = Path(directory) / "profile"
            browser._policy = BrowserPolicy()
            browser._extension_registry = BrowserExtensionRegistry(
                Path(directory) / "extensions.json", Path(directory)
            )
            self.assertFalse(browser._requires_developer_startup_sync())
            browser.profile_dir.mkdir()
            (browser.profile_dir / "koba-browser-policy.json").write_text("{}")
            self.assertFalse(browser._requires_developer_startup_sync())
            (browser.profile_dir / "Default").mkdir()
            self.assertTrue(browser._requires_developer_startup_sync())
            (browser.profile_dir / "Default").rmdir()
            with patch.object(
                browser._extension_registry, "load_paths", return_value=["/private/extension"]
            ):
                self.assertTrue(browser._requires_developer_startup_sync())
            browser._policy.developer_access_enabled = True
            self.assertTrue(browser._requires_developer_startup_sync())
