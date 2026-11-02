"""Concrete data already published by the retained administration event stream."""

from collections.abc import Callable

from domain.realtime import (
    AccountIdentity,
    AccountVerified,
    BrowserDebugIssued,
    BrowserPolicyFailure,
    BrowserUnavailable,
    MetricsHeartbeat,
)
from domain.telemetry import InvocationBatch

from common.access_contracts import AccessLifecycleDetails, ResolvedAccessRequest, SessionSnapshot
from common.account_contracts import AccountPublic
from common.browser_contracts import BrowserStatus, ExternalBrowserStatus, PageSummary
from modules.workspace_compat.domain.receipts import WorkspaceDelete, WorkspaceEntry

from .analysis_views import (
    AnalysisProjectDeleted,
    AnalysisProjectOpened,
    AnalysisProjectReleased,
    AnalysisWorkerChanged,
)
from .dashboard_state import DashboardState
from .panel_views import (
    CallsDeleted,
    ItemDeleted,
    RecordsRemoved,
    SettingsSnapshot,
    WorkerQueueClearedView,
    WorkerRecoveredView,
)
from .terminal_views import JobCleanup, JobDeleted, JobStatus, WorkspaceDeleted
from .web_session_contracts import WebSessionRevoked, WebUserControls

type RealtimeDetails = (
    AccountPublic
    | AccountVerified
    | AccountIdentity
    | InvocationBatch
    | DashboardState
    | MetricsHeartbeat
    | BrowserStatus
    | BrowserUnavailable
    | BrowserDebugIssued
    | BrowserPolicyFailure
    | PageSummary
    | ExternalBrowserStatus
    | WorkspaceEntry
    | WorkspaceDelete
    | JobStatus
    | JobDeleted
    | JobCleanup
    | WorkspaceDeleted
    | AnalysisProjectOpened
    | AnalysisProjectReleased
    | AnalysisProjectDeleted
    | AnalysisWorkerChanged
    | WorkerQueueClearedView
    | WorkerRecoveredView
    | CallsDeleted
    | ItemDeleted
    | RecordsRemoved
    | SettingsSnapshot
    | AccessLifecycleDetails
    | ResolvedAccessRequest
    | SessionSnapshot
    | WebSessionRevoked
    | WebUserControls
)

type RealtimePublisher = Callable[[str, str, RealtimeDetails], None]
