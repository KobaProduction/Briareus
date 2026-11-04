from __future__ import annotations

from briareus_environment_models import ProcessSettings
from pydantic import Field, field_validator
from sqlalchemy.engine import URL


class ControlPanelSettings(ProcessSettings):
    postgres_username: str = Field("postgres", validation_alias="POSTGRES_USERNAME")
    postgres_password: str = Field("", validation_alias="POSTGRES_PASSWORD", repr=False)
    postgres_database: str = Field("briareus", validation_alias="POSTGRES_DATABASE")
    encryption_key: str = Field("", validation_alias="CONTROL_PANEL_ENCRYPTION_KEY")
    service_token: str = Field("", validation_alias="CONTROL_PANEL_SERVICE_TOKEN")
    session_secret: str = Field("", validation_alias="CONTROL_PANEL_SESSION_SECRET")
    session_https_only: bool = Field(
        True,
        validation_alias="CONTROL_PANEL_SESSION_HTTPS_ONLY",
    )
    frontend_telemetry_upstream_url: str = Field(
        "",
        validation_alias="CONTROL_PANEL_FRONTEND_TELEMETRY_UPSTREAM_URL",
    )
    frontend_telemetry_bearer_token: str = Field(
        "",
        validation_alias="CONTROL_PANEL_FRONTEND_TELEMETRY_BEARER_TOKEN",
    )

    @field_validator(
        "encryption_key",
        "service_token",
        "session_secret",
        "frontend_telemetry_upstream_url",
        "frontend_telemetry_bearer_token",
        mode="before",
    )
    @classmethod
    def _strip_secrets(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @property
    def database_url(self) -> str:
        return URL.create(
            "postgresql+psycopg",
            username=self.postgres_username,
            password=self.postgres_password,
            host="postgres",
            port=5432,
            database=self.postgres_database,
        ).render_as_string(hide_password=False)

    def validate_bootstrap(self) -> None:
        missing = [
            name
            for name, value in (
                ("CONTROL_PANEL_ENCRYPTION_KEY", self.encryption_key),
                ("CONTROL_PANEL_SERVICE_TOKEN", self.service_token),
                ("CONTROL_PANEL_SESSION_SECRET", self.session_secret),
                ("POSTGRES_USERNAME", self.postgres_username),
                ("POSTGRES_PASSWORD", self.postgres_password),
                ("POSTGRES_DATABASE", self.postgres_database),
            )
            if not value
        ]
        if missing:
            raise ValueError("missing management bootstrap settings: " + ", ".join(missing))
