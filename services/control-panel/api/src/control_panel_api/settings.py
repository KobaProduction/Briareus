from __future__ import annotations

from typing import Literal

from briareus_environment_models import ProcessSettings
from pydantic import Field, field_validator
from sqlalchemy.engine import URL


class ControlPanelSettings(ProcessSettings):
    database_backend: Literal["postgresql", "sqlite"] = Field(
        "postgresql", validation_alias="CONTROL_PANEL_DATABASE_BACKEND"
    )
    sqlite_path: str = Field("", validation_alias="CONTROL_PANEL_SQLITE_PATH")
    postgres_host: str = Field("postgres", validation_alias="POSTGRES_HOST")
    postgres_port: int = Field(5432, ge=1, le=65535, validation_alias="POSTGRES_PORT")
    postgres_username: str = Field("postgres", validation_alias="POSTGRES_USERNAME")
    postgres_password: str = Field("", validation_alias="POSTGRES_PASSWORD", repr=False)
    postgres_database: str = Field("briareus", validation_alias="POSTGRES_DATABASE")
    encryption_key: str = Field("", validation_alias="CONTROL_PANEL_ENCRYPTION_KEY")
    service_token: str = Field("", validation_alias="BRIAREUS_SERVICE_TOKEN")
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
        "frontend_telemetry_upstream_url",
        "frontend_telemetry_bearer_token",
        mode="before",
    )
    @classmethod
    def _strip_secrets(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @property
    def database_url(self) -> str:
        if self.database_backend == "sqlite":
            if not self.sqlite_path.strip():
                raise ValueError("CONTROL_PANEL_SQLITE_PATH is required for SQLite")
            return URL.create("sqlite+pysqlite", database=self.sqlite_path).render_as_string()
        return URL.create(
            "postgresql+psycopg",
            username=self.postgres_username,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_database,
        ).render_as_string(hide_password=False)

    def validate_bootstrap(self) -> None:
        if self.database_backend == "sqlite" and not self.sqlite_path.strip():
            raise ValueError("missing management bootstrap settings: CONTROL_PANEL_SQLITE_PATH")
        required_postgres = (
            (
                ("POSTGRES_USERNAME", self.postgres_username),
                ("POSTGRES_PASSWORD", self.postgres_password),
                ("POSTGRES_DATABASE", self.postgres_database),
                ("POSTGRES_HOST", self.postgres_host),
            )
            if self.database_backend == "postgresql"
            else ()
        )
        missing = [
            name
            for name, value in (
                ("CONTROL_PANEL_ENCRYPTION_KEY", self.encryption_key),
                ("BRIAREUS_SERVICE_TOKEN", self.service_token),
                *required_postgres,
            )
            if not value
        ]
        if missing:
            raise ValueError("missing management bootstrap settings: " + ", ".join(missing))
