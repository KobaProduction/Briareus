from __future__ import annotations

from urllib.parse import urlsplit

from briareus_environment_models import ProcessSettings
from pydantic import Field, field_validator
from pydantic_settings import SettingsConfigDict


class ValkeySettings(ProcessSettings):
    model_config = SettingsConfigDict(hide_input_in_errors=True)

    url: str = Field("redis://valkey:6379/0", validation_alias="VALKEY_URL")
    username: str = Field(
        "default", pattern=r"^[a-zA-Z0-9_-]+$", validation_alias="VALKEY_USERNAME"
    )
    password: str = Field(min_length=1, validation_alias="VALKEY_PASSWORD", repr=False)
    namespace: str = Field("briareus:v1", validation_alias="VALKEY_NAMESPACE")
    socket_connect_timeout_seconds: float = Field(
        0.15,
        ge=0.01,
        le=5.0,
        validation_alias="VALKEY_CONNECT_TIMEOUT_SECONDS",
    )
    socket_timeout_seconds: float = Field(
        0.25,
        ge=0.01,
        le=5.0,
        validation_alias="VALKEY_SOCKET_TIMEOUT_SECONDS",
    )
    failure_backoff_seconds: float = Field(
        5.0,
        ge=0.1,
        le=60.0,
        validation_alias="VALKEY_FAILURE_BACKOFF_SECONDS",
    )
    account_ttl_seconds: int = Field(
        120, ge=1, le=3600, validation_alias="VALKEY_ACCOUNT_TTL_SECONDS"
    )
    account_list_ttl_seconds: int = Field(
        30, ge=1, le=600, validation_alias="VALKEY_ACCOUNT_LIST_TTL_SECONDS"
    )
    policy_ttl_seconds: int = Field(30, ge=1, le=600, validation_alias="VALKEY_POLICY_TTL_SECONDS")
    management_config_ttl_seconds: int = Field(
        30,
        ge=1,
        le=600,
        validation_alias="VALKEY_CONTROL_PANEL_CONFIG_TTL_SECONDS",
    )

    @field_validator("url", "namespace", "username", mode="before")
    @classmethod
    def _strip_cache_strings(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("url")
    @classmethod
    def _separate_cache_credentials(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("Use VALKEY_USERNAME/VALKEY_PASSWORD; VALKEY_URL owns topology only")
        return value
