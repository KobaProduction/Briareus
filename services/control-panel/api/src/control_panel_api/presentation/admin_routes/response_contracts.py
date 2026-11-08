from __future__ import annotations

from typing import Literal

from briareus_browser_policy import BrowserRuntimePolicy
from briareus_github_policy import GitHubRuntimePolicy
from briareus_gitlab_policy import GitLabRuntimePolicy
from briareus_json_values import JsonObject, ProviderModel, StrictModel, json_object
from briareus_mcp_policy import McpRuntimePolicy
from briareus_terminal_policy import TerminalRuntimePolicy
from pydantic import field_serializer

from control_panel_api.domain.accounts import Provider
from control_panel_api.domain.configuration import ControlPanelConfig
from control_panel_api.domain.telemetry import Invocation


class AccountDeletion(StrictModel):
    deleted: Literal[True] = True
    id: str
    provider: Provider


class CandidateVerification(StrictModel):
    ok: Literal[True] = True
    provider: Provider
    draft_revision: str


class CallsPage(StrictModel):
    events: list[Invocation]
    count: int
    total: int
    limit: int
    offset: int
    has_more: bool
    next_cursor: str


class DeletedCount(StrictModel):
    deleted: int


class CallDeletion(StrictModel):
    deleted: Literal[True] = True
    id: str


class RemovedCount(StrictModel):
    removed: int


class ReverseSessionSettings(ProviderModel):
    idle_timeout_seconds: float = 900.0
    auto_release_enabled: bool = True
    source: str = ""


class SettingsSnapshot(StrictModel):
    management: ControlPanelConfig
    terminal: TerminalRuntimePolicy
    mcp: McpRuntimePolicy
    browser: BrowserRuntimePolicy
    github: GitHubRuntimePolicy
    gitlab: GitLabRuntimePolicy
    analysis: ReverseSessionSettings
    analysis_error: str = ""
    revision: str = ""

    @field_serializer("analysis")
    def serialize_analysis(self, value: ReverseSessionSettings) -> JsonObject:
        return json_object(value.model_dump(mode="json", exclude_unset=True))


class SettingsVersion(StrictModel):
    management: ControlPanelConfig
    terminal: TerminalRuntimePolicy
    mcp: McpRuntimePolicy
    browser: BrowserRuntimePolicy
    github: GitHubRuntimePolicy
    gitlab: GitLabRuntimePolicy
    analysis_idle_timeout_seconds: float


class BrowserPolicyDisconnectFailure(StrictModel):
    error: str
