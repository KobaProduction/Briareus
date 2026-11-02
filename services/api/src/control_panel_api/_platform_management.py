"""Composition for cookie-bound human Platform management."""

from fastapi import APIRouter

from ._api_paths import API_V1_PREFIX
from ._oidc_membership import CurrentPlatformContext
from ._panel_events import panel_events
from ._platform_unix_peer import UnixPlatformPeer
from .application.platform_management import HumanPlatformManagement
from .infrastructure.platform_management import PlatformManagementEvents, PlatformManagementOwner
from .presentation.platform_commands import PlatformCommand as PlatformCommand
from .presentation.platform_management import PlatformManagementController


def platform_management_router(
    *, current_context: CurrentPlatformContext, peer: UnixPlatformPeer | None, browser_origin: str
) -> APIRouter:
    owner = PlatformManagementOwner(peer) if peer is not None else None
    use_case = HumanPlatformManagement(owner, PlatformManagementEvents(panel_events))
    controller = PlatformManagementController(current_context, use_case, origin=browser_origin)
    router = APIRouter(prefix=API_V1_PREFIX + "/platform")
    router.add_api_route("/inventory", controller.inventory, methods=["GET"])
    router.add_api_route("/commands", controller.command, methods=["POST"])
    return router
