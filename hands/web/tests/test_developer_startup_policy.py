"""Only a genuinely pristine, non-developer profile can use Chrome defaults."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from modules.web.browser import BrowserManager


class DeveloperStartupPolicyTests(unittest.TestCase):
    def test_existing_state_and_requested_extensions_keep_policy_sync(self):
        with TemporaryDirectory() as directory:
            browser = object.__new__(BrowserManager)
            browser.profile_dir = Path(directory) / "profile"
            browser._developer_access_enabled = False
            browser._extension_registry = SimpleNamespace(load_paths=lambda: [])
            self.assertFalse(browser._requires_developer_startup_sync())
            browser.profile_dir.mkdir()
            (browser.profile_dir / "koba-browser-policy.json").write_text("{}")
            self.assertFalse(browser._requires_developer_startup_sync())
            (browser.profile_dir / "Default").mkdir()
            self.assertTrue(browser._requires_developer_startup_sync())
            (browser.profile_dir / "Default").rmdir()
            browser._extension_registry = SimpleNamespace(load_paths=lambda: ["/private/extension"])
            self.assertTrue(browser._requires_developer_startup_sync())
            browser._extension_registry = SimpleNamespace(load_paths=lambda: [])
            browser._developer_access_enabled = True
            self.assertTrue(browser._requires_developer_startup_sync())
