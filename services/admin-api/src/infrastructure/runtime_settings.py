"""Adapt the existing policy services and browser client to settings ports."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from domain.configuration import AdminConfig
from domain.realtime import BrowserPolicyFailure
from domain.runtime_changes import BrowserTokenChange

from common.runtime_policy_contracts import (
    BrowserRuntimePolicy,
    GitHubRuntimePolicy,
    GitLabRuntimePolicy,
    McpRuntimePolicy,
    TerminalRuntimePolicy,
)

if TYPE_CHECKING:
    from application.analysis_views import AnalysisSessionSettings
    from application.panel_views import SettingsSnapshot
    from application.realtime_details import RealtimeDetails
    from application.services import AdminConfigService, RuntimeSettingsService
    from realtime import RealtimeBus

    from infrastructure.reverse import ReverseAdminClient
    from infrastructure.web import WebAdminClient


@dataclass(frozen=True, slots=True)
class LegacyRuntimeSettingsStore:
    config: "AdminConfigService"
    runtime: "RuntimeSettingsService"

    async def admin(self) -> AdminConfig:
        return await self.config.get()

    async def terminal(self) -> TerminalRuntimePolicy:
        return await self.runtime.terminal_policy()

    async def mcp(self) -> McpRuntimePolicy:
        return await self.runtime.mcp_policy()

    async def browser(self) -> BrowserRuntimePolicy:
        return await self.runtime.browser_policy()

    async def github(self) -> GitHubRuntimePolicy:
        return await self.runtime.github_policy()

    async def gitlab(self) -> GitLabRuntimePolicy:
        return await self.runtime.gitlab_policy()

    async def save_admin(self, policy: AdminConfig) -> AdminConfig:
        return await self.config.update(policy)

    async def save_terminal(self, policy: TerminalRuntimePolicy) -> TerminalRuntimePolicy:
        return await self.runtime.update_terminal_policy(policy)

    async def save_mcp(self, policy: McpRuntimePolicy) -> McpRuntimePolicy:
        return await self.runtime.update_mcp_policy(policy)

    async def save_browser(
        self, policy: BrowserRuntimePolicy, token: BrowserTokenChange
    ) -> BrowserRuntimePolicy:
        return await self.runtime.update_browser_policy(
            policy, extension_token=token.token, clear_extension_token=token.clear
        )

    async def save_github(self, policy: GitHubRuntimePolicy) -> GitHubRuntimePolicy:
        return await self.runtime.update_github_policy(policy)

    async def save_gitlab(self, policy: GitLabRuntimePolicy) -> GitLabRuntimePolicy:
        return await self.runtime.update_gitlab_policy(policy)


@dataclass(frozen=True, slots=True)
class LegacyBrowserRuntimeChanges:
    web: "WebAdminClient"
    realtime: "RealtimeBus | None"

    async def disconnect(self) -> None:
        await self.web.external_disconnect()

    async def disconnect_failed(self, message: str) -> None:
        if self.realtime is not None:
            await self.realtime.publish(
                "browser.runtime",
                "external.policy_disconnect_failed",
                BrowserPolicyFailure(message),
            )


@dataclass(frozen=True, slots=True)
class LegacyWebReverseSettings:
    reverse: "ReverseAdminClient"

    async def read(self) -> "AnalysisSessionSettings":
        return await self.reverse.session_settings()

    async def update(self, seconds: float) -> "AnalysisSessionSettings":
        return await self.reverse.set_idle_timeout(seconds)


@dataclass(frozen=True, slots=True)
class LegacyAdminWebEvents:
    realtime: "RealtimeBus | None"

    async def publish(self, event_type: str, data: "RealtimeDetails") -> None:
        if self.realtime is not None:
            await self.realtime.publish("admin.events", event_type, data)

    async def updated(self, settings: "SettingsSnapshot") -> None:
        await self.publish("settings.updated", settings)
