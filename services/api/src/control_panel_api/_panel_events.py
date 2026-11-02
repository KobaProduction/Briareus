"""Established Panel broker and authenticated event endpoint composition."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter

from runtime_peer import PeerClient

from ._oidc_membership import CurrentPlatformContext
from ._platform_unix_peer import UnixPlatformPeer
from ._realtime_bus import PanelEvents
from .infrastructure.panel_authority import CurrentPanelUser
from .presentation.panel_events import panel_events_router as compose_panel_events_router

if TYPE_CHECKING:
    from ._runtime_access_client import RuntimeAccessClient

panel_events = PanelEvents()


def panel_events_router(
    *,
    current_context: CurrentPlatformContext,
    current_user: CurrentPanelUser,
    access: RuntimeAccessClient | None = None,
    platform: UnixPlatformPeer | None = None,
    resources: PeerClient | None = None,
) -> APIRouter:
    return compose_panel_events_router(
        current_context=current_context,
        current_user=current_user,
        broker=panel_events,
        access=access,
        platform=platform,
        resources=resources,
    )
