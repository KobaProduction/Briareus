"""Named panel response contracts; serialization belongs to HTTP/event adapters."""

import json
from dataclasses import asdict
from hashlib import sha256
from typing import Literal

from domain.configuration import AdminConfig
from pydantic import BaseModel

from application.analysis_views import (
    AnalysisOpenProgram,
    AnalysisProjectFiles,
    AnalysisProjectSession,
    AnalysisReadModel,
    AnalysisSessionSettings,
    AnalysisSettingsUnavailable,
    AnalysisWorker,
    AnalysisWorkerQueueCleared,
    AnalysisWorkerRecovered,
)
from application.terminal_views import JobRead, JobStatus
from common.browser_contracts import DebugTarget
from common.runtime_policy_contracts import (
    BrowserRuntimePolicy,
    GitHubRuntimePolicy,
    GitLabRuntimePolicy,
    McpRuntimePolicy,
    TerminalRuntimePolicy,
)

from .invocation_contracts import InvocationDocument


class NavigationItem(BaseModel):
    id: str
    label: str
    enabled: bool


class PanelBootstrap(BaseModel):
    product: str
    environment: str
    navigation: list[NavigationItem]


class ItemDeleted(BaseModel):
    deleted: bool
    id: str


class AccountDeleted(ItemDeleted):
    provider: str


class CallsDeleted(BaseModel):
    deleted: int


class RecordsRemoved(BaseModel):
    removed: int


class PanelCallPage(BaseModel):
    events: list[InvocationDocument]
    count: int
    total: int
    limit: int
    offset: int
    has_more: bool
    next_cursor: str


class TerminalJobView(BaseModel):
    job: JobStatus
    tail: JobRead


class InactiveAnalysisFiles(AnalysisReadModel):
    """The existing empty file response while a project has no active worker."""


class AnalysisProjectView(AnalysisReadModel):
    session: AnalysisProjectSession
    files: AnalysisProjectFiles | InactiveAnalysisFiles
    programs: list[AnalysisOpenProgram]
    folder: str


class AnalysisWorkers(BaseModel):
    workers: list[AnalysisWorker]
    count: int


class WorkerActionView(AnalysisReadModel):
    worker: AnalysisWorker


class WorkerQueueClearedView(WorkerActionView):
    operation: Literal["clear_queue"] = "clear_queue"
    result: AnalysisWorkerQueueCleared


class WorkerRecoveredView(WorkerActionView):
    operation: Literal["recover"] = "recover"
    result: AnalysisWorkerRecovered


class BrowserRemoteDebug(DebugTarget):
    expires_in_seconds: int
    websocket_url: str
    frontend_url: str
    devtools_url: str


class SettingsSnapshot(BaseModel):
    admin: AdminConfig
    terminal: TerminalRuntimePolicy
    mcp: McpRuntimePolicy
    browser: BrowserRuntimePolicy
    github: GitHubRuntimePolicy
    gitlab: GitLabRuntimePolicy
    analysis: AnalysisSessionSettings | AnalysisSettingsUnavailable
    analysis_error: str
    revision: str = ""

    def revision_value(self) -> str:
        versioned = {
            "admin": asdict(self.admin),
            "terminal": self.terminal.model_dump(mode="json"),
            "mcp": self.mcp.model_dump(mode="json"),
            "browser": self.browser.model_dump(mode="json"),
            "github": self.github.model_dump(mode="json"),
            "gitlab": self.gitlab.model_dump(mode="json"),
            "analysis_idle_timeout_seconds": self.analysis.idle_timeout_seconds,
        }
        encoded = json.dumps(versioned, sort_keys=True, separators=(",", ":")).encode()
        return sha256(encoded).hexdigest()
