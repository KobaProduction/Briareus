from __future__ import annotations

import os

from briareus_zitadel_tokens import ZitadelTokenSettings
from pydantic import Field


class GatewayAuthSettings(ZitadelTokenSettings):
    enabled: bool = Field(True, validation_alias="OAUTH_ENABLED")
    public_base_url: str = Field("", validation_alias="MCP_PUBLIC_BASE_URL")

    def validate_bootstrap(self) -> None:
        if not self.enabled:
            if os.environ.get("DEPLOYMENT_ENVIRONMENT") != "test":
                raise ValueError("User authentication may only be disabled in isolated tests")
            return
        super().validate_bootstrap()
        if not self.public_base_url:
            raise ValueError("MCP_PUBLIC_BASE_URL is required")
