"""Browser management contracts owned by the control panel, not a tool implementation."""

from typing import Literal

from briareus_json_values import StrictModel
from pydantic import Field


class BrowserViewport(StrictModel):
    width: int
    height: int


class BrowserPage(StrictModel):
    page_id: str
    label: str = ""
    page_agent_access: bool = True
    agent_access: bool = True
    locked: bool = False
    url: str = ""
    title: str = ""


class BrowserViewportResult(BrowserPage):
    viewport: BrowserViewport
    requested_viewport: BrowserViewport


class BrowserCapabilities(StrictModel):
    set_viewport: bool
    set_theme: bool
    remote_devtools: bool


class BrowserTabPolicy(StrictModel):
    max_tabs: int
    idle_close_enabled: bool
    idle_timeout_seconds: int


class BrowserExtension(StrictModel):
    id: str
    path: str


class BrowserBrand(StrictModel):
    brand: str
    version: str


class BrowserGraphics(StrictModel):
    vendor: str
    renderer: str


class BrowserObservedRuntime(StrictModel):
    user_agent: str = ""
    user_agent_brands: list[BrowserBrand] = Field(default_factory=list)
    language: str = ""
    languages: list[str] = Field(default_factory=list)
    intl_locale: str = ""
    timezone: str = ""
    webdriver: bool = False
    webgl: BrowserGraphics | None = None
    webgl2: BrowserGraphics | None = None
    screen: BrowserViewport | None = None


class BrowserStatus(StrictModel):
    running: bool
    process_running: bool = False
    manually_stopped: bool = False
    cdp_reachable: bool = False
    context_usable: bool = False
    agent_access_enabled: bool = True
    developer_access_enabled: bool = False
    developer_access_effective: bool = False
    developer_backend: str = "cdp"
    developer_backend_connected: bool = False
    headless: bool = True
    browser: str = "chromium"
    capabilities: BrowserCapabilities | None = None
    color_scheme: Literal["system", "light", "dark"] = "system"
    locale: str = ""
    accept_language: str = ""
    display: str = ""
    xvfb_enabled: bool = False
    timezone: str = ""
    posix_locale: str = ""
    chromium_args: list[str] = Field(default_factory=list)
    executable_path: str = ""
    profile_dir: str = ""
    dev_extensions: list[BrowserExtension] = Field(default_factory=list)
    managed_user_scripts_extension_count: int = 0
    user_scripts_follow_developer_access: bool = True
    user_scripts_sync_error: str = ""
    observed: BrowserObservedRuntime = Field(default_factory=BrowserObservedRuntime)
    tab_policy: BrowserTabPolicy | None = None
    page_count: int = 0
    pages: list[BrowserPage] = Field(default_factory=list)
    updated_pages: int | None = None
    native_ui_restart_required: bool | None = None


class BrowserDebugTarget(StrictModel):
    page_id: str
    target_id: str
    title: str
    url: str


class BrowserRemoteDebug(BrowserDebugTarget):
    websocket_path: str
    protocol: Literal["briareus.v1"] = "briareus.v1"


class BrowserDebugIssued(StrictModel):
    page_id: str
    target_id: str


class BrowserStopResult(StrictModel):
    stopped: bool
    profile_preserved: bool


class ExternalBrowserError(StrictModel):
    code: str
    stage: str
    message: str
    next_action: str
    retryable: bool
    http_status: int | None = None


class ExternalBrowserStatus(StrictModel):
    phase: str
    connecting: bool
    tool_count: int | None
    configured: bool
    enabled: bool
    provider: str
    namespace: str
    endpoint_origin: str
    connected: bool
    proxy_connected: bool
    connection_state: str
    session_scope: str
    other_client_sessions: str
    grant_state: str
    tab_access_state: str
    browser_ready: bool | None
    last_successful_tab_probe_at: str
    last_error: ExternalBrowserError | None
    next_action: str
    session_connect_count: int
    last_activity_at: str
    call_timeout_seconds: float
    auto_disconnect_enabled: bool
    idle_timeout_seconds: float
    profile_dir_name: str
    extension_token_configured: bool


class ExternalBrowserAction(ExternalBrowserStatus):
    ok: bool | None


class BrowserUnavailable(StrictModel):
    available: Literal[False] = False
    reason: str = ""
    error: str = ""
