"""Typed browser provider observations; optional page fields are serialized only when set."""

from __future__ import annotations

from pydantic import Field

from runtime_peer.browser_receipts import (
    BrowserBrand as BrowserBrand,
)
from runtime_peer.browser_receipts import (
    BrowserDiagnostics as BrowserDiagnostics,
)
from runtime_peer.browser_receipts import (
    BrowserObservation as BrowserObservation,
)
from runtime_peer.browser_receipts import (
    BrowserPages as BrowserPages,
)
from runtime_peer.browser_receipts import (
    BrowserStatus as BrowserStatus,
)
from runtime_peer.browser_receipts import (
    Capabilities as Capabilities,
)
from runtime_peer.browser_receipts import (
    ClosedPage as ClosedPage,
)
from runtime_peer.browser_receipts import (
    DebugTarget as DebugTarget,
)
from runtime_peer.browser_receipts import (
    Dimensions as Dimensions,
)
from runtime_peer.browser_receipts import (
    EmptyObservation as EmptyObservation,
)
from runtime_peer.browser_receipts import (
    GraphicsObservation as GraphicsObservation,
)
from runtime_peer.browser_receipts import (
    PageSummary as PageSummary,
)
from runtime_peer.browser_receipts import (
    SnapshotElement as SnapshotElement,
)
from service_runtime.models import StrictModel


class AgentAccessStatus(StrictModel):
    agent_access_enabled: bool
    developer_access_effective: bool


class OperatorLease(StrictModel):
    owner_token: str
    selected_page_id: str


class OperatorState(StrictModel):
    control: str
    selected_page_id: str
    pages: list[PageSummary]
    page_count: int
    operator_count: int
    agent_access_enabled: bool
    developer_access_enabled: bool
    developer_access_effective: bool
    developer_backend: str
    can_reopen_closed_tab: bool
    capabilities: Capabilities
    color_scheme: str
    viewport: Dimensions
    screen: Dimensions


class CleanBrowserResult(StrictModel):
    cleaned: bool
    agent_access_enabled: bool
    developer_access_enabled: bool
    developer_access_effective: bool
    selected_page_id: str
    page_count: int


class DeveloperExtensionResult(StrictModel):
    id: str
    user_scripts_access: bool = Field(alias="userScriptsAccess")
    ok: bool
    error: str | None = None


class ChromiumDeveloperObservation(StrictModel):
    in_developer_mode: bool | None = Field(alias="inDeveloperMode")
    extensions: list[DeveloperExtensionResult]
    eligible_extension_ids: list[str] = Field(alias="eligibleExtensionIds")


class DeveloperSyncResult(StrictModel):
    in_developer_mode: bool | None
    user_scripts_enabled: bool
    user_scripts_extension_count: int
    extensions: list[DeveloperExtensionResult]


class DeveloperExtensionReceipt(DeveloperSyncResult):
    extension_id: str
    user_scripts_managed: bool


class DeveloperAccessReceipt(DeveloperSyncResult):
    developer_access_enabled: bool
    developer_access_effective: bool
