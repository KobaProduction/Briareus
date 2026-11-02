from __future__ import annotations

from common.control_panel_client import ControlPanelClient
from common.identity_provider import ZitadelClient
from common.identity_settings import McpAuthSettings, ZitadelSettings
from common.observability import announce_runtime_started, build_observability
from common.settings import ControlPanelClientSettings

from .api import build_auth_app
from .provider import MultiResourceZitadelProvider

settings = McpAuthSettings()
settings.validate_bootstrap()
_observability = build_observability("auth")
announce_runtime_started(_observability, "auth")

management = ControlPanelClient(ControlPanelClientSettings())
identity_provider = ZitadelClient(ZitadelSettings())
identity_provider.metadata()
provider = MultiResourceZitadelProvider(settings, identity_provider, management)
app = build_auth_app(provider)
