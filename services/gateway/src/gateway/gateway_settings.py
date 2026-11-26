from __future__ import annotations

import os

from briareus_oidc import OidcTokenSettings
from pydantic import AliasChoices, Field

from .settings import GatewaySettings


class GatewayAuthSettings(OidcTokenSettings):
    browser_client_id: str = Field("", validation_alias="OIDC_BROWSER_CLIENT_ID")
    enabled: bool = Field(True, validation_alias="OAUTH_ENABLED")
    public_base_url: str = Field(
        "", validation_alias=AliasChoices("SERVICE_URL_GATEWAY", "MCP_PUBLIC_BASE_URL")
    )

    def validate_bootstrap(self) -> None:
        if not self.enabled:
            if os.environ.get("DEPLOYMENT_ENVIRONMENT") != "test":
                raise ValueError("User authentication may only be disabled in isolated tests")
            return
        super().validate_bootstrap()
        if not self.public_base_url:
            raise ValueError("SERVICE_URL_GATEWAY or MCP_PUBLIC_BASE_URL is required")
        GatewaySettings.http_for_origin(self.public_base_url)
