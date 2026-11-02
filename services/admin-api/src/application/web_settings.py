"""Read and update legacy web settings through the existing owner collaborators."""

import asyncio
from typing import Protocol

from domain.configuration import AdminConfig

from application.analysis_views import AnalysisSessionSettings, AnalysisSettingsUnavailable
from application.panel_views import SettingsSnapshot
from application.runtime_settings import (
    CurrentRuntimePolicies,
    PrepareRuntimeSettings,
    RuntimeSettingsWriteError,
    SaveRuntimeSettings,
)
from application.settings_command import SettingsPayload
from common.runtime_policy_contracts import (
    BrowserRuntimePolicy,
    GitHubRuntimePolicy,
    GitLabRuntimePolicy,
    McpRuntimePolicy,
    TerminalRuntimePolicy,
)


class WebSettingsPolicies(Protocol):
    async def admin(self) -> AdminConfig: ...
    async def terminal(self) -> TerminalRuntimePolicy: ...
    async def mcp(self) -> McpRuntimePolicy: ...
    async def browser(self) -> BrowserRuntimePolicy: ...
    async def github(self) -> GitHubRuntimePolicy: ...
    async def gitlab(self) -> GitLabRuntimePolicy: ...


class WebReverseSettings(Protocol):
    async def read(self) -> AnalysisSessionSettings: ...
    async def update(self, seconds: float) -> AnalysisSessionSettings: ...


class WebSettingsEvents(Protocol):
    async def updated(self, settings: SettingsSnapshot) -> None: ...


class WebSettingsRejected(Exception):
    """The same policy/reverse write rejection exposed by the retained web surface."""


class WebSettingsConflict(Exception):
    def __init__(self, current_revision: str) -> None:
        super().__init__("settings changed since they were loaded; reload before saving")
        self.current_revision = current_revision


class WebSettingsSnapshotReader:
    """Application collaborator used by both the settings read and update scenarios."""

    def __init__(self, policies: WebSettingsPolicies, reverse: WebReverseSettings) -> None:
        self._policies = policies
        self._reverse = reverse

    async def read(self) -> SettingsSnapshot:
        config, terminal, mcp, browser, github, gitlab = await asyncio.gather(
            self._policies.admin(),
            self._policies.terminal(),
            self._policies.mcp(),
            self._policies.browser(),
            self._policies.github(),
            self._policies.gitlab(),
        )
        reverse_settings: AnalysisSessionSettings | AnalysisSettingsUnavailable
        try:
            reverse_settings = await self._reverse.read()
            reverse_error = ""
        except Exception as exc:
            reverse_settings = AnalysisSettingsUnavailable(
                idle_timeout_seconds=900.0,
                auto_release_enabled=True,
                source="unavailable",
            )
            reverse_error = str(exc)
        snapshot = SettingsSnapshot(
            admin=config,
            terminal=terminal,
            mcp=mcp,
            browser=browser,
            github=github,
            gitlab=gitlab,
            analysis=reverse_settings,
            analysis_error=reverse_error,
        )
        snapshot.revision = snapshot.revision_value()
        return snapshot


class UpdateWebSettings:
    def __init__(
        self,
        reader: WebSettingsSnapshotReader,
        prepare: PrepareRuntimeSettings,
        save: SaveRuntimeSettings,
        reverse: WebReverseSettings,
        events: WebSettingsEvents,
        lock: asyncio.Lock,
    ) -> None:
        self._reader = reader
        self._prepare = prepare
        self._save = save
        self._reverse = reverse
        self._events = events
        self._lock = lock

    async def execute(self, payload: SettingsPayload) -> SettingsSnapshot:
        async with self._lock:
            current: SettingsSnapshot | None = None
            if payload.expected_revision:
                try:
                    current = await self._reader.read()
                except (ValueError, RuntimeError) as exc:
                    raise WebSettingsRejected(str(exc)) from exc
                if payload.expected_revision != current.revision:
                    raise WebSettingsConflict(current.revision)
            current_policies = (
                None
                if current is None
                else CurrentRuntimePolicies(current.browser, current.github, current.gitlab)
            )
            try:
                change = await self._prepare.prepare(payload, current_policies)
                reverse_settings = await self._reverse.update(payload.reverse_idle_timeout_seconds)
            except (ValueError, RuntimeError) as exc:
                raise WebSettingsRejected(str(exc)) from exc
            try:
                saved = await self._save.execute(change)
            except RuntimeSettingsWriteError as exc:
                raise WebSettingsRejected(str(exc)) from exc
            response = SettingsSnapshot(
                admin=saved.admin,
                terminal=saved.terminal,
                mcp=saved.mcp,
                browser=saved.browser,
                github=saved.github,
                gitlab=saved.gitlab,
                analysis=reverse_settings,
                analysis_error="",
            )
            response.revision = response.revision_value()
            await self._events.updated(response)
            return response
