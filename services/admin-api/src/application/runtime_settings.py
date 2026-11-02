"""Prepare partial runtime changes and persist them through explicit owner ports."""

import asyncio
from dataclasses import dataclass
from typing import Protocol

from domain.configuration import AdminConfig
from domain.runtime_changes import BrowserTokenChange

from common.runtime_policy_contracts import (
    BrowserRuntimePolicy,
    GitHubRuntimePolicy,
    GitLabRuntimePolicy,
    McpRuntimePolicy,
    TerminalRuntimePolicy,
)

from .settings_command import SettingsPayload


@dataclass(frozen=True, slots=True)
class CurrentRuntimePolicies:
    browser: BrowserRuntimePolicy
    github: GitHubRuntimePolicy
    gitlab: GitLabRuntimePolicy


@dataclass(frozen=True, slots=True)
class RuntimePolicyValues:
    admin: AdminConfig
    terminal: TerminalRuntimePolicy
    mcp: McpRuntimePolicy
    browser: BrowserRuntimePolicy
    github: GitHubRuntimePolicy
    gitlab: GitLabRuntimePolicy


@dataclass(frozen=True, slots=True)
class RuntimeSettingsChange:
    policies: RuntimePolicyValues
    previous_browser: BrowserRuntimePolicy
    browser_token: BrowserTokenChange


class RuntimeSettingsStore(Protocol):
    async def browser(self) -> BrowserRuntimePolicy: ...
    async def github(self) -> GitHubRuntimePolicy: ...
    async def gitlab(self) -> GitLabRuntimePolicy: ...
    async def save_admin(self, policy: AdminConfig) -> AdminConfig: ...
    async def save_terminal(self, policy: TerminalRuntimePolicy) -> TerminalRuntimePolicy: ...
    async def save_mcp(self, policy: McpRuntimePolicy) -> McpRuntimePolicy: ...
    async def save_browser(
        self, policy: BrowserRuntimePolicy, token: BrowserTokenChange
    ) -> BrowserRuntimePolicy: ...
    async def save_github(self, policy: GitHubRuntimePolicy) -> GitHubRuntimePolicy: ...
    async def save_gitlab(self, policy: GitLabRuntimePolicy) -> GitLabRuntimePolicy: ...


class BrowserRuntimeChanges(Protocol):
    async def disconnect(self) -> None: ...
    async def disconnect_failed(self, message: str) -> None: ...


class RuntimeSettingsWriteError(Exception):
    """A legacy policy owner rejected a write before browser notification."""


def browser_policy(command: SettingsPayload, current: BrowserRuntimePolicy) -> BrowserRuntimePolicy:
    fields = command.model_fields_set
    return BrowserRuntimePolicy(
        external_enabled=command.browser_external_enabled
        if "browser_external_enabled" in fields
        else current.external_enabled,
        external_mcp_url=command.browser_external_mcp_url
        if "browser_external_mcp_url" in fields
        else current.external_mcp_url,
        call_timeout_seconds=command.browser_call_timeout_seconds
        if "browser_call_timeout_seconds" in fields
        else current.call_timeout_seconds,
        auto_disconnect_enabled=command.browser_auto_disconnect_enabled
        if "browser_auto_disconnect_enabled" in fields
        else current.auto_disconnect_enabled,
        idle_timeout_seconds=command.browser_idle_timeout_seconds
        if "browser_idle_timeout_seconds" in fields
        else current.idle_timeout_seconds,
        profile_dir_name=command.browser_profile_dir_name
        if "browser_profile_dir_name" in fields
        else current.profile_dir_name,
        extension_token_configured=current.extension_token_configured,
    )


def github_policy(command: SettingsPayload, current: GitHubRuntimePolicy) -> GitHubRuntimePolicy:
    fields = command.model_fields_set
    return GitHubRuntimePolicy(
        local_first_guidance=command.github_local_first_guidance
        if "github_local_first_guidance" in fields
        else current.local_first_guidance,
        local_git_transport_enabled=command.github_local_git_transport_enabled
        if "github_local_git_transport_enabled" in fields
        else current.local_git_transport_enabled,
        remote_source_mutations_enabled=command.github_remote_source_mutations_enabled
        if "github_remote_source_mutations_enabled" in fields
        else current.remote_source_mutations_enabled,
    )


def gitlab_policy(command: SettingsPayload, current: GitLabRuntimePolicy) -> GitLabRuntimePolicy:
    fields = command.model_fields_set
    return GitLabRuntimePolicy(
        local_first_guidance=command.gitlab_local_first_guidance
        if "gitlab_local_first_guidance" in fields
        else current.local_first_guidance,
        local_git_transport_enabled=command.gitlab_local_git_transport_enabled
        if "gitlab_local_git_transport_enabled" in fields
        else current.local_git_transport_enabled,
        remote_source_mutations_enabled=command.gitlab_remote_source_mutations_enabled
        if "gitlab_remote_source_mutations_enabled" in fields
        else current.remote_source_mutations_enabled,
    )


class PrepareRuntimeSettings:
    """Application collaborator retaining omitted-policy values before any writes."""

    def __init__(self, store: RuntimeSettingsStore) -> None:
        self.store = store

    async def github_current(
        self, command: SettingsPayload, current: CurrentRuntimePolicies | None
    ) -> GitHubRuntimePolicy:
        if {
            "github_local_first_guidance",
            "github_local_git_transport_enabled",
            "github_remote_source_mutations_enabled",
        }.issubset(command.model_fields_set):
            return GitHubRuntimePolicy()
        return current.github if current is not None else await self.store.github()

    async def gitlab_current(
        self, command: SettingsPayload, current: CurrentRuntimePolicies | None
    ) -> GitLabRuntimePolicy:
        if {
            "gitlab_local_first_guidance",
            "gitlab_local_git_transport_enabled",
            "gitlab_remote_source_mutations_enabled",
        }.issubset(command.model_fields_set):
            return GitLabRuntimePolicy()
        return current.gitlab if current is not None else await self.store.gitlab()

    async def prepare(
        self, command: SettingsPayload, current: CurrentRuntimePolicies | None = None
    ) -> RuntimeSettingsChange:
        old_browser = current.browser if current is not None else await self.store.browser()
        browser = browser_policy(command, old_browser)
        token = BrowserTokenChange.requested(
            command.browser_extension_token,
            supplied="browser_extension_token" in command.model_fields_set,
            clear=command.browser_clear_extension_token,
        )
        github = github_policy(command, await self.github_current(command, current))
        gitlab = gitlab_policy(command, await self.gitlab_current(command, current))
        values = RuntimePolicyValues(
            AdminConfig(
                logging_enabled=command.logging_enabled,
                logging_capture_payloads=command.logging_capture_payloads,
                logging_retention_days=command.logging_retention_days,
                logging_max_records=command.logging_max_records,
                maintenance_interval_minutes=command.maintenance_interval_minutes,
            ),
            TerminalRuntimePolicy(
                max_exec_timeout_seconds=command.terminal_max_exec_timeout_seconds,
                max_job_runtime_seconds=command.terminal_max_job_runtime_seconds,
            ),
            McpRuntimePolicy(call_timeout_seconds=command.mcp_call_timeout_seconds),
            browser,
            github,
            gitlab,
        )
        return RuntimeSettingsChange(values, old_browser, token)


class SaveRuntimeSettings:
    """Application collaborator persisting prepared policies and browser notifications."""

    def __init__(self, store: RuntimeSettingsStore, browser: BrowserRuntimeChanges) -> None:
        self.store = store
        self.browser = browser

    async def persist(self, change: RuntimeSettingsChange) -> RuntimePolicyValues:
        values = change.policies
        admin, terminal, mcp, browser, github, gitlab = await asyncio.gather(
            self.store.save_admin(values.admin),
            self.store.save_terminal(values.terminal),
            self.store.save_mcp(values.mcp),
            self.store.save_browser(values.browser, change.browser_token),
            self.store.save_github(values.github),
            self.store.save_gitlab(values.gitlab),
        )
        return RuntimePolicyValues(admin, terminal, mcp, browser, github, gitlab)

    async def execute(self, change: RuntimeSettingsChange) -> RuntimePolicyValues:
        try:
            saved = await self.persist(change)
        except (ValueError, RuntimeError) as exc:
            raise RuntimeSettingsWriteError(str(exc)) from exc
        if saved.browser != change.previous_browser:
            try:
                await self.browser.disconnect()
            except Exception as exc:
                await self.browser.disconnect_failed(str(exc))
        return saved
