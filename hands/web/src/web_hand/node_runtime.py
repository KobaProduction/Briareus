"""The existing Web tools, composed only inside the unprivileged Node child.

No Control Panel client, global runtime or credential source is imported here.
The browser profile and its downloaded files belong to one placement only.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path
from typing import NamedTuple

from fastmcp import FastMCP
from mcp.types import Tool

from common.runtime_annotations import READ_EXTERNAL, WRITE_EXTERNAL
from common.runtime_policy_contracts import BrowserRuntimePolicy
from common.settings import BrowserSettings
from modules.web.browser import BrowserManager
from modules.web.browser_profile import DEFAULT_BROWSER_DESKTOP_PROFILE, resolve_chromium_gpu_args
from modules.web.browser_tools import register_browser_tools
from modules.web.devtools_proxy import DevToolsProxyRuntime
from modules.web.external_browser_proxy import ExternalBrowserProxyRuntime
from modules.web.external_browser_tools import register_external_tools
from modules.workspace_compat.legacy_store import WorkspaceFileStore

EGRESS = "http://web-egress:8080"
LOCAL_TOOLS = frozenset(
    {
        "browser_diagnostics",
        "browser_status",
        "browser_restart",
        "browser_pages",
        "browser_reopen_closed_page",
        "browser_settings",
        "browser_input",
        "browser_open",
        "browser_set_theme",
        "browser_debug_target",
        "browser_set_viewport",
        "browser_set_page_label",
        "browser_snapshot",
        "browser_click",
        "browser_fill",
        "browser_press",
        "browser_select_option",
        "browser_upload",
        "browser_download",
        "browser_screenshot",
        "browser_preview",
        "browser_wait",
        "browser_back",
        "browser_forward",
        "browser_reload",
        "browser_close_page",
    }
)
STATIC_TOOLS = frozenset("local_" + name for name in LOCAL_TOOLS) | frozenset(
    {"external_status", "external_connect", "external_disconnect", "external_reset"}
)


def browser_metadata(metadata: Sequence[Tool]) -> list[Tool]:
    return [
        tool
        for tool in metadata
        if "curl" not in tool.name.casefold()
        and (tool.name in STATIC_TOOLS or tool.name.startswith(("local_devtools_", "external_")))
    ]


class BrowserRuntime(NamedTuple):
    mcp: FastMCP[None]
    browser: BrowserManager
    devtools: DevToolsProxyRuntime[None]
    external: ExternalBrowserProxyRuntime[None]


def create_runtime() -> BrowserRuntime:
    if os.environ.get("BRIAREUS_NODE_WEB_EGRESS") != EGRESS:
        raise ValueError("Pinned Node public-only browser egress required")
    root = Path("/browser")
    if root.is_symlink() or root.stat().st_uid != 1000 or root.stat().st_mode & 0o077:
        raise ValueError("Placement-private browser storage required")
    workspace: WorkspaceFileStore
    if os.environ.get("BRIAREUS_NODE_WEB_PROJECT_WORKSPACE", "0") == "1":
        from .project_workspace import ProjectBrowserWorkspace

        workspace = ProjectBrowserWorkspace(
            Path("/workspace/project"),
            root / "workspace",
            read_only=os.environ.get("BRIAREUS_NODE_WEB_PROJECT_READ_ONLY") == "1",
        )
    else:
        workspace = WorkspaceFileStore(root / "workspace")
    workspace.ensure()
    profile_root = Path(os.environ["BRIAREUS_NODE_WEB_PROFILE"])
    if (
        profile_root.parent != root
        or not profile_root.name.startswith("session-")
        or profile_root.is_symlink()
    ):
        raise ValueError("Supervisor-selected private browser session required")
    profile_root.mkdir(mode=0o700, exist_ok=True)
    if profile_root.stat().st_uid != 1000 or profile_root.stat().st_mode & 0o077:
        raise ValueError("Owner-private browser session required")
    from hand_runtime.runtime_policy import runtime_policy

    limits = runtime_policy()
    settings = BrowserSettings()
    profile = DEFAULT_BROWSER_DESKTOP_PROFILE
    browser = BrowserManager(
        workspace=workspace,
        profile_dir=profile_root / "profile",
        executable_path=settings.executable_path,
        headless=profile.headless,
        timeout_ms=int(limits.execution_timeout_seconds * 1000)
        if limits.execution_timeout_seconds is not None
        else 0,
        viewport_width=profile.viewport_width,
        viewport_height=profile.viewport_height,
        screen_width=profile.screen_width,
        screen_height=profile.screen_height,
        locale=profile.locale,
        accept_language=profile.accept_language,
        display=profile.display,
        color_depth=profile.color_depth,
        xvfb_enabled=profile.xvfb_enabled,
        timezone=settings.timezone,
        posix_locale=profile.posix_locale,
        chromium_args=(
            *profile.chromium_args,
            *resolve_chromium_gpu_args(),
            "--proxy-server=" + EGRESS,
            "--proxy-bypass-list=<-loopback>",
            "--disable-quic",
            "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE web-egress",
        ),
        max_snapshot_text_chars=settings.max_snapshot_text_chars,
        max_snapshot_elements=settings.max_snapshot_elements,
        developer_access_enabled=os.environ.get("BRIAREUS_NODE_WEB_DEVELOPER_ACCESS") == "1",
    )
    mcp = FastMCP[None]("briareus-node-browsers")
    local = FastMCP[None]("local-managed-browser")
    register_browser_tools(local, READ_EXTERNAL, WRITE_EXTERNAL, browser=browser)
    mcp.mount(local, namespace="local")
    devtools = DevToolsProxyRuntime[None](browser, settings, workspace=workspace.root)
    mcp.mount(devtools.server, namespace="local_devtools")
    # The former runtime fetched policy from Core, exposing a private route to
    # browser code. This immutable placement policy contains no Core credential.
    policy = BrowserRuntimePolicy.model_validate_json(
        os.environ.get("BRIAREUS_NODE_WEB_POLICY", "{}")
    )

    async def external_policy() -> BrowserRuntimePolicy:
        return policy

    external = ExternalBrowserProxyRuntime[None](external_policy)
    mcp.mount(external.server, namespace="external")

    register_external_tools(mcp, external)
    return BrowserRuntime(mcp, browser, devtools, external)
