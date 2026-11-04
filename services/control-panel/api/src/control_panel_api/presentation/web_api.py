from fastapi import APIRouter

from control_panel_api.application.identity import PanelIdentityService
from control_panel_api.settings import ControlPanelSettings

from .admin_routes.accounts import AccountsRoutes
from .admin_routes.analysis import AnalysisRoutes
from .admin_routes.browser import BrowserRoutes
from .admin_routes.calls import CallsRoutes
from .admin_routes.context import WebApiContext
from .admin_routes.contracts import WebApiServices as WebApiServices
from .admin_routes.files import FilesRoutes
from .admin_routes.overview import OverviewRoutes
from .admin_routes.settings import SettingsRoutes
from .admin_routes.telemetry import TelemetryRoutes
from .admin_routes.terminal import TerminalRoutes


def build_admin_api_router(
    settings: ControlPanelSettings,
    services: WebApiServices | None = None,
    *,
    identity: PanelIdentityService,
    public_origin: str,
) -> APIRouter:
    router = APIRouter(prefix="/admin/api", tags=["admin"])
    context = WebApiContext(settings, services, identity, public_origin)
    OverviewRoutes(context).register(router)
    AccountsRoutes(context).register(router)
    CallsRoutes(context).register(router)
    FilesRoutes(context).register(router)
    TerminalRoutes(context).register(router)
    AnalysisRoutes(context).register(router)
    BrowserRoutes(context).register(router)
    TelemetryRoutes(context).register(router)
    SettingsRoutes(context).register(router)
    return router
