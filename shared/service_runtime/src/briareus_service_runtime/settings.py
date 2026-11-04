from __future__ import annotations

from briareus_environment_models import ProcessSettings
from pydantic import Field, field_validator


class AsgiServerSettings(ProcessSettings):
    app: str = Field("gateway.server:app", validation_alias="ASGI_APP")
    host: str = Field("0.0.0.0", validation_alias="ASGI_HOST")
    port: int = Field(8000, ge=1, le=65535, validation_alias="ASGI_PORT")
    workers: int = Field(1, ge=1, le=8, validation_alias="ASGI_WORKERS")
    forwarded_allow_ips: str = Field(
        "127.0.0.1",
        validation_alias="ASGI_FORWARDED_ALLOW_IPS",
    )

    @field_validator("app", "host", "forwarded_allow_ips", mode="before")
    @classmethod
    def _strip_values(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value
