from __future__ import annotations

from briareus_environment_models import ProcessSettings
from pydantic import Field, field_validator


class ControlPanelClientSettings(ProcessSettings):
    url: str = Field("http://control-panel-api:8000", validation_alias="CONTROL_PANEL_URL")
    service_token: str = Field("", validation_alias="CONTROL_PANEL_SERVICE_TOKEN")
    timeout_seconds: float = Field(
        10,
        gt=0,
        le=60,
        validation_alias="CONTROL_PANEL_TIMEOUT_SECONDS",
    )

    @field_validator("url", "service_token", mode="before")
    @classmethod
    def _strip_values(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value
