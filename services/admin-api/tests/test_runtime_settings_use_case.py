"""Partial policy writes preserve omitted values and explicit credential intent."""

import unittest
from dataclasses import dataclass, field

from application.runtime_settings import (
    CurrentRuntimePolicies,
    PrepareRuntimeSettings,
    RuntimeSettingsWriteError,
    SaveRuntimeSettings,
)
from application.settings_command import SettingsPayload
from domain.configuration import AdminConfig
from domain.runtime_changes import BrowserTokenChange

from common.runtime_policy_contracts import (
    BrowserRuntimePolicy,
    GitHubRuntimePolicy,
    GitLabRuntimePolicy,
    McpRuntimePolicy,
    TerminalRuntimePolicy,
)


@dataclass
class StoreFixture:
    browser_value: BrowserRuntimePolicy = field(
        default_factory=lambda: BrowserRuntimePolicy(
            call_timeout_seconds=123, extension_token_configured=True, profile_dir_name="Existing"
        )
    )
    github_value: GitHubRuntimePolicy = field(
        default_factory=lambda: GitHubRuntimePolicy(
            local_first_guidance=False, remote_source_mutations_enabled=True
        )
    )
    gitlab_value: GitLabRuntimePolicy = field(
        default_factory=lambda: GitLabRuntimePolicy(local_git_transport_enabled=False)
    )
    reads: list[str] = field(default_factory=list)
    writes: list[str] = field(default_factory=list)
    token_change: BrowserTokenChange | None = None
    reject_mcp: bool = False

    async def browser(self) -> BrowserRuntimePolicy:
        self.reads.append("browser")
        return self.browser_value

    async def github(self) -> GitHubRuntimePolicy:
        self.reads.append("github")
        return self.github_value

    async def gitlab(self) -> GitLabRuntimePolicy:
        self.reads.append("gitlab")
        return self.gitlab_value

    async def save_admin(self, policy: AdminConfig) -> AdminConfig:
        self.writes.append("admin")
        return policy

    async def save_terminal(self, policy: TerminalRuntimePolicy) -> TerminalRuntimePolicy:
        self.writes.append("terminal")
        return policy

    async def save_mcp(self, policy: McpRuntimePolicy) -> McpRuntimePolicy:
        if self.reject_mcp:
            raise ValueError("fixture policy rejected")
        self.writes.append("mcp")
        return policy

    async def save_browser(
        self, policy: BrowserRuntimePolicy, token: BrowserTokenChange
    ) -> BrowserRuntimePolicy:
        self.writes.append("browser")
        self.token_change = token
        return policy

    async def save_github(self, policy: GitHubRuntimePolicy) -> GitHubRuntimePolicy:
        self.writes.append("github")
        return policy

    async def save_gitlab(self, policy: GitLabRuntimePolicy) -> GitLabRuntimePolicy:
        self.writes.append("gitlab")
        return policy


@dataclass
class BrowserFixture:
    fail_disconnect: bool = False
    fail_report: bool = False
    disconnected: int = 0
    errors: list[str] = field(default_factory=list)

    async def disconnect(self) -> None:
        self.disconnected += 1
        if self.fail_disconnect:
            raise RuntimeError("fixture disconnect unavailable")

    async def disconnect_failed(self, message: str) -> None:
        if self.fail_report:
            raise RuntimeError("fixture reporting unavailable")
        self.errors.append(message)


class RuntimeSettingsTests(unittest.IsolatedAsyncioTestCase):
    async def test_omitted_fields_preserve_current_runtime_values(self) -> None:
        store = StoreFixture()
        change = await PrepareRuntimeSettings(store).prepare(SettingsPayload())
        self.assertEqual(change.policies.browser, store.browser_value)
        self.assertEqual(change.policies.github, store.github_value)
        self.assertEqual(change.policies.gitlab, store.gitlab_value)
        self.assertEqual(store.reads, ["browser", "github", "gitlab"])
        self.assertEqual(store.writes, [])

    async def test_explicit_false_overrides_current_value(self) -> None:
        store = StoreFixture()
        command = SettingsPayload(github_remote_source_mutations_enabled=False)
        change = await PrepareRuntimeSettings(store).prepare(command)
        self.assertFalse(change.policies.github.remote_source_mutations_enabled)
        self.assertFalse(change.policies.github.local_first_guidance)

    async def test_complete_source_policies_need_no_provider_read(self) -> None:
        store = StoreFixture()
        command = SettingsPayload(
            github_local_first_guidance=True,
            github_local_git_transport_enabled=True,
            github_remote_source_mutations_enabled=False,
            gitlab_local_first_guidance=True,
            gitlab_local_git_transport_enabled=True,
            gitlab_remote_source_mutations_enabled=False,
        )
        await PrepareRuntimeSettings(store).prepare(command)
        self.assertEqual(store.reads, ["browser"])

    async def test_cas_snapshot_is_used_without_another_policy_read(self) -> None:
        store = StoreFixture()
        current = CurrentRuntimePolicies(
            store.browser_value, store.github_value, store.gitlab_value
        )
        change = await PrepareRuntimeSettings(store).prepare(SettingsPayload(), current)
        self.assertEqual(change.policies.browser, current.browser)
        self.assertEqual(store.reads, [])

    async def test_set_and_clear_token_is_rejected_before_writes(self) -> None:
        store = StoreFixture()
        supplied = "fixture"
        command = SettingsPayload(
            browser_extension_token=supplied, browser_clear_extension_token=True
        )
        with self.assertRaisesRegex(ValueError, "cannot set and clear"):
            await PrepareRuntimeSettings(store).prepare(command)
        self.assertEqual(store.writes, [])

    async def test_blank_token_can_clear_and_unchanged_browser_stays_connected(self) -> None:
        store, browser = StoreFixture(), BrowserFixture()
        blank = " "
        command = SettingsPayload(browser_extension_token=blank, browser_clear_extension_token=True)
        change = await PrepareRuntimeSettings(store).prepare(command)
        await SaveRuntimeSettings(store, browser).execute(change)
        self.assertEqual(store.token_change, BrowserTokenChange(None, True))
        self.assertEqual(browser.disconnected, 0)
        self.assertEqual(
            set(store.writes), {"admin", "terminal", "mcp", "browser", "github", "gitlab"}
        )

    async def test_saved_policy_change_disconnects_after_all_policy_writes(self) -> None:
        store, browser = StoreFixture(), BrowserFixture()
        change = await PrepareRuntimeSettings(store).prepare(
            SettingsPayload(browser_profile_dir_name="New")
        )
        result = await SaveRuntimeSettings(store, browser).execute(change)
        self.assertEqual(result.browser.profile_dir_name, "New")
        self.assertEqual(browser.disconnected, 1)
        self.assertEqual(len(store.writes), 6)

    async def test_disconnect_failure_is_reported_without_undoing_saved_policy(self) -> None:
        store, browser = StoreFixture(), BrowserFixture(fail_disconnect=True)
        change = await PrepareRuntimeSettings(store).prepare(
            SettingsPayload(browser_profile_dir_name="New")
        )
        result = await SaveRuntimeSettings(store, browser).execute(change)
        self.assertEqual(result.browser.profile_dir_name, "New")
        self.assertEqual(browser.errors, ["fixture disconnect unavailable"])

    async def test_write_rejection_does_not_disconnect_browser(self) -> None:
        store, browser = StoreFixture(reject_mcp=True), BrowserFixture()
        change = await PrepareRuntimeSettings(store).prepare(
            SettingsPayload(browser_profile_dir_name="New")
        )
        with self.assertRaisesRegex(RuntimeSettingsWriteError, "fixture policy rejected"):
            await SaveRuntimeSettings(store, browser).execute(change)
        self.assertEqual(browser.disconnected, 0)

    async def test_notification_failure_is_not_reclassified_as_policy_write_failure(self) -> None:
        store = StoreFixture()
        browser = BrowserFixture(fail_disconnect=True, fail_report=True)
        change = await PrepareRuntimeSettings(store).prepare(
            SettingsPayload(browser_profile_dir_name="New")
        )
        with self.assertRaisesRegex(RuntimeError, "fixture reporting unavailable"):
            await SaveRuntimeSettings(store, browser).execute(change)
