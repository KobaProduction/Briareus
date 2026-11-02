"""Optional signed Web MCP browser observation, NOT the deployed Web entrypoint.

The normal web_hand.server stays diagnostic-only. A trusted supervisor must
supply an independently authenticated private decision peer, a genuine
Project-owned browser-session resolver, and an isolated browser observer.
Legacy global BrowserManager/CDP and external user's Chrome are never imported.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import UUID

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import CallToolResult, TextContent
from starlette.applications import Starlette

from hand_runtime import (
    EffectAuthorizationMiddleware,
    EffectResolver,
    ProtectedHandTools,
    ToolEffectBinding,
    TrustedPrivateDecisionPort,
    create_diagnostic_hand_app,
)

from .application.read_snapshot import ReadBrowserSnapshot, TrustedBrowserSnapshotPort
from .domain.browser_snapshot import (
    BrowserSnapshot,
    BrowserSnapshotRequest,
    require_public_snapshot,
)

_BROWSER_HANDLE = re.compile(r"[a-z0-9][a-z0-9_-]{0,127}\Z", re.ASCII)
_MAX_TEXT_CHARS = 4096


@dataclass(frozen=True, slots=True)
class TrustedWebBrowserPorts:
    """Source-only trusted assembly inputs; no environment or MCP user fallback."""

    effect_resolver: EffectResolver
    private_decision: TrustedPrivateDecisionPort
    snapshots: TrustedBrowserSnapshotPort

    def __post_init__(self) -> None:
        if not all(
            callable(item)
            for item in (
                self.effect_resolver,
                getattr(self.private_decision, "decide", None),
                getattr(self.snapshots, "read_snapshot", None),
                getattr(self.snapshots, "validate_current", None),
            )
        ):
            raise ValueError("browser observation requires all trusted owner ports")


def _canonical_uuid(values: list[str]) -> UUID:
    if len(values) != 1:
        raise ValueError("missing or repeated selector")
    result = UUID(values[0])
    if result.version != 4 or str(result) != values[0]:
        raise ValueError("noncanonical UUIDv4 selector")
    return result


def _request_for_owner(browser_handle: str, max_text_chars: int) -> BrowserSnapshotRequest:
    """Capture original signed actor selectors again after the private PDP.

    The worker is an independent trust boundary: this is its input, not a
    declaration that the browser context actually belongs to the actor.
    """
    if (
        _BROWSER_HANDLE.fullmatch(browser_handle) is None
        or type(max_text_chars) is not int
        or not 1 <= max_text_chars <= _MAX_TEXT_CHARS
    ):
        raise ValueError("unverified browser snapshot scope")
    # Recheck SDK signed resource purpose, token expiry and the CURRENT
    # ASGI raw header scope, never Starlette's cached Request.headers.
    bearer, request = EffectAuthorizationMiddleware._verified_request()
    project, agent_session, revision = EffectAuthorizationMiddleware._request_selectors(request)
    return BrowserSnapshotRequest(
        bearer.removeprefix("Bearer "),
        project,
        agent_session,
        revision,
        browser_handle,
        max_text_chars,
    )


def _public_snapshot(snapshot: object, max_chars: int) -> BrowserSnapshot:
    return require_public_snapshot(snapshot, max_chars)


def build_protected_web_browser_app(ports: TrustedWebBrowserPorts) -> Starlette:
    """Stage one read-only effect; never called by deployed web_hand.server.

    The resolver must bind the caller handle to a real owner Project,
    browser lease and immutable canonical arguments. The authenticated private
    Cedar port must attest that exact effect. The isolated browser worker MUST
    recheck actor/lease and Project mapping immediately before observation.
    """
    if not isinstance(ports, TrustedWebBrowserPorts):
        raise ValueError("trusted Web ports must be supplied by a supervisor")

    def register(mcp: FastMCP[None]) -> None:
        @mcp.tool(
            name="browser_snapshot",
            title="Read a Project-scoped browser snapshot",
            annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
            run_in_thread=False,
        )
        async def browser_snapshot(
            browser_handle: str, max_text_chars: int = 2048
        ) -> CallToolResult:
            try:
                result = await ReadBrowserSnapshot(
                    ports.snapshots,
                    lambda: _request_for_owner(browser_handle, max_text_chars),
                ).execute(max_text_chars)
                payload = asdict(result)
                return CallToolResult(
                    content=[TextContent(type="text", text=json.dumps(payload))],
                    structured_content=payload,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                # Never expose bearer, Project ID, browser data or worker details.
                raise ToolError("WEB_BROWSER_OWNER_OR_AUTHORIZATION_UNAVAILABLE") from None

    return create_diagnostic_hand_app(
        hand="web",
        source_root=Path(__file__).resolve().parents[1],
        unavailable_code="WEB_OAUTH_AUTHORIZATION_UNAVAILABLE",
        health_fields={"authorization": "owner_ports_injected_unaccepted"},
        protected_tools=ProtectedHandTools(
            register=register,
            effect_bindings={
                "browser_snapshot": ToolEffectBinding(
                    "web.access", "browser_session", ports.effect_resolver
                )
            },
            private_decision=ports.private_decision,
        ),
    )
