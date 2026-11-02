"""Browser observations shared by MCP producers and panel consumers; no runtime dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class BrowserRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)


@dataclass(frozen=True, slots=True)
class DevExtension:
    id: str
    path: str


class Dimensions(BrowserRecord):
    width: int
    height: int


class Capabilities(BrowserRecord):
    set_viewport: bool
    set_theme: bool
    remote_devtools: bool


class SnapshotElement(BrowserRecord):
    ref: str
    tag: str
    role: str
    type: str
    name: str
    href: str
    value: str
    disabled: bool


class PageSummary(BrowserRecord):
    page_id: str
    label: str
    page_agent_access: bool
    agent_access: bool
    url: str
    title: str
    locked: bool | None = None
    http_status: int | None = None
    selected: list[str] | None = None
    workspace_path: str | None = None
    viewport: Dimensions | None = None
    requested_viewport: Dimensions | None = None
    reopened: bool | None = None
    cleaned_app: bool | None = None
    cleaned_origin: str | None = None
    deleted_cookie_count: int | None = None
    text: str | None = None
    text_truncated: bool | None = None
    elements: list[SnapshotElement] | None = None
    element_count: int | None = None


class EmptyObservation(BrowserRecord):
    pass


class BrowserBrand(BrowserRecord):
    brand: str
    version: str


class GraphicsObservation(BrowserRecord):
    vendor: str
    renderer: str


class BrowserObservation(BrowserRecord):
    user_agent: str
    user_agent_brands: list[BrowserBrand]
    language: str
    languages: list[str]
    intl_locale: str
    timezone: str
    webdriver: bool | None
    webgl: GraphicsObservation | None
    webgl2: GraphicsObservation | None
    screen: Dimensions


class BrowserStatus(BrowserRecord):
    running: bool
    process_running: bool
    cdp_reachable: bool
    context_usable: bool
    agent_access_enabled: bool
    developer_access_enabled: bool
    developer_access_effective: bool
    developer_backend: str
    developer_backend_connected: bool
    headless: bool
    browser: str
    capabilities: Capabilities
    color_scheme: str
    locale: str
    accept_language: str
    display: str
    xvfb_enabled: bool
    timezone: str
    posix_locale: str
    chromium_args: list[str]
    executable_path: str
    profile_dir: str
    dev_extensions: tuple[DevExtension, ...]
    managed_user_scripts_extension_count: int
    user_scripts_follow_developer_access: bool
    user_scripts_sync_error: str
    observed: BrowserObservation | EmptyObservation
    page_count: int
    pages: list[PageSummary]
    updated_pages: int | None = None
    native_ui_restart_required: bool | None = None


class DebugTarget(BrowserRecord):
    page_id: str
    target_id: str
    title: str
    url: str


class ExternalBrowserStatus(BaseModel):
    configured: bool
    enabled: bool
    provider: Literal["playwright-mcp"] = "playwright-mcp"
    namespace: Literal["external"] = "external"
    endpoint_origin: str
    connected: bool
    session_connect_count: int
    last_activity_at: str
    call_timeout_seconds: int | None
    auto_disconnect_enabled: bool
    idle_timeout_seconds: int
    profile_dir_name: str
    extension_token_configured: bool
    tool_count: int | None = None
    browser_ready: bool | None = None


class BrowserDiagnostics(BrowserRecord):
    executable_path: str
    profile_dir: str
    version_exit_code: int
    version_stdout: str
    version_stderr: str
    probe_exit_code: int
    probe_stdout: str
    probe_stderr: str


class BrowserPages(BrowserRecord):
    count: int
    pages: list[PageSummary]


class LocalBrowserPages(BrowserPages):
    can_reopen_closed_tab: bool | None = None


class BrowserPreview(BrowserRecord):
    page_id: str
    url: str
    title: str
    mime_type: str
    data_base64: str


class BrowserInteractionReceipt(BrowserRecord):
    inventory: LocalBrowserPages
    snapshot: PageSummary
    preview: BrowserPreview


class ClosedPage(BrowserRecord):
    page_id: str
    closed: bool


class BrowserPendingOperation(BrowserRecord):
    operation_id: str = Field(min_length=1, max_length=128)
    tool: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")


class BrowserStarting(BrowserRecord):
    pending: BrowserPendingOperation | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    running: Literal[False] = False
    starting: Literal[True] = True
    cdp_reachable: Literal[False] = False


class BrowserPreparingReceipt(BrowserRecord):
    result: BrowserStarting


type BrowserReceipt = (
    BrowserStatus
    | LocalBrowserPages
    | BrowserPreview
    | ClosedPage
    | PageSummary
    | BrowserInteractionReceipt
)


BROWSER_RESULTS: dict[str, type[BrowserReceipt]] = {
    "local_browser_status": BrowserStatus,
    "local_browser_pages": LocalBrowserPages,
    "local_browser_reopen_closed_page": PageSummary,
    "local_browser_settings": PageSummary,
    "local_browser_input": BrowserInteractionReceipt,
    "local_browser_open": PageSummary,
    "local_browser_snapshot": PageSummary,
    "local_browser_back": PageSummary,
    "local_browser_forward": PageSummary,
    "local_browser_reload": PageSummary,
    "local_browser_close_page": ClosedPage,
    "local_browser_set_viewport": PageSummary,
    "local_browser_click": PageSummary,
    "local_browser_fill": PageSummary,
    "local_browser_press": PageSummary,
    "local_browser_select_option": PageSummary,
    "local_browser_preview": BrowserPreview,
}


type BrowserOperationState = Literal["running", "interrupted", "cancelled", "failed", "completed"]


class BrowserOperationReceipt[State: str, Reply](BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    operation_id: str
    tool: str
    state: State
    result: Reply | None = None


class BrowserInspectionResult(BaseModel):
    page: PageSummary
    snapshot: PageSummary


class BrowserCallReceipt(BaseModel):
    operation_uuid: UUID
    result: BrowserInspectionResult
