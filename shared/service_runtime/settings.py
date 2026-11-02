from __future__ import annotations

import re
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as distribution_version
from socket import gethostname
from typing import Annotated, ClassVar, Protocol
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_DEFAULT_PRIVATE_HOSTS = (
    "localhost:*",
    "127.0.0.1:*",
    "[::1]:*",
    "github:*",
    "gitlab:*",
    "files:*",
    "web:*",
    "analysis:*",
    "ghidra:*",
    "terminal:*",
    "observability:*",
    "authorization:*",
)


_DEFAULT_PRIVATE_ORIGINS = (
    "http://localhost:*",
    "http://127.0.0.1:*",
    "http://[::1]:*",
)


def _csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _strip_string(value: object) -> object:
    return value.strip() if isinstance(value, str) else value


def _tuple_value(value: object) -> object:
    return _csv(value) if isinstance(value, str) else value


def _frozenset_value(value: object) -> object:
    if isinstance(value, str):
        return frozenset(item.casefold() for item in _csv(value))
    if isinstance(value, (set, frozenset, tuple, list)):
        return frozenset(str(item).casefold() for item in value)
    return value


class FrozenSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HttpSurfaceSettings(FrozenSettings):
    allowed_hosts: tuple[str, ...]
    allowed_origins: tuple[str, ...]


class _HttpSurfaceSource(Protocol):
    @property
    def allowed_hosts(self) -> tuple[str, ...]: ...

    @property
    def allowed_origins(self) -> tuple[str, ...]: ...


class _HttpSurfaceAccess:
    @property
    def http(self: _HttpSurfaceSource) -> HttpSurfaceSettings:
        return HttpSurfaceSettings(
            allowed_hosts=self.allowed_hosts,
            allowed_origins=self.allowed_origins,
        )


class ProcessSettings(BaseSettings):
    """Immutable environment-backed configuration created only by composition roots."""

    model_config = SettingsConfigDict(
        extra="ignore",
        case_sensitive=True,
        env_file=None,
        validate_default=True,
        populate_by_name=True,
        frozen=True,
    )


class AsgiServerSettings(ProcessSettings):
    app: str = Field("bridge.server:app", validation_alias="ASGI_APP")
    host: str = Field("0.0.0.0", validation_alias="ASGI_HOST")  # noqa: S104 -- intentional container listener; exposure is configured by the owner
    port: int = Field(8000, ge=1, le=65535, validation_alias="ASGI_PORT")
    forwarded_allow_ips: str = Field(
        "127.0.0.1",
        validation_alias="ASGI_FORWARDED_ALLOW_IPS",
    )

    _strip_values = field_validator("app", "host", "forwarded_allow_ips", mode="before")(
        staticmethod(_strip_string)
    )


class PrivateRuntimeSettings(_HttpSurfaceAccess, ProcessSettings):
    allowed_hosts: Annotated[tuple[str, ...], NoDecode] = Field(
        _DEFAULT_PRIVATE_HOSTS,
        validation_alias="PRIVATE_MCP_ALLOWED_HOSTS",
    )
    allowed_origins: Annotated[tuple[str, ...], NoDecode] = Field(
        _DEFAULT_PRIVATE_ORIGINS,
        validation_alias="PRIVATE_MCP_ALLOWED_ORIGINS",
    )

    _parse_csv = field_validator("allowed_hosts", "allowed_origins", mode="before")(
        staticmethod(_tuple_value)
    )


class ValkeySettings(ProcessSettings):
    url: str = Field("redis://valkey:6379/0", validation_alias="VALKEY_URL")
    namespace: str = Field("mcp-bridge:v1", validation_alias="VALKEY_NAMESPACE")
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
    admin_config_ttl_seconds: int = Field(
        30,
        ge=1,
        le=600,
        validation_alias="VALKEY_ADMIN_API_CONFIG_TTL_SECONDS",
    )

    _strip_cache_strings = field_validator("url", "namespace", mode="before")(
        staticmethod(_strip_string)
    )


class ObservabilitySettings(ProcessSettings):
    """Briareus-only OpenTelemetry identity with one canonical OTLP endpoint.

    D4 controls the Project/Environment shared identity and the per-release
    application service.name. Version and instance are actual local release /
    container facts, never a mutable shared environment override. No legacy
    OTEL_ENVIRONMENT, exporter endpoint-per-signal, OTEL headers or
    resource-attributes alias can silently defeat scope redaction.
    """

    service_name: str = Field("", validation_alias="OTEL_SERVICE_NAME")
    service_namespace: str = Field("briareus", validation_alias="SERVICE_NAMESPACE")
    environment: str = Field("development", validation_alias="DEPLOYMENT_ENVIRONMENT")
    endpoint: str = Field("", validation_alias="OTLP_ENDPOINT")
    bearer_token: SecretStr | None = Field(default=None, validation_alias="OTLP_BEARER_TOKEN")
    # Stable implementation limits, NOT another operator ENV surface.
    timeout_ms: ClassVar[int] = 10_000
    metric_export_interval_ms: ClassVar[int] = 30_000
    log_level: ClassVar[str] = "INFO"

    @field_validator("service_name")
    @classmethod
    def _service_name(cls, value: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9-]{1,63}", value) and value != "":
            raise ValueError("OTEL_SERVICE_NAME must identify one Briareus application")
        return value

    @field_validator("service_namespace")
    @classmethod
    def _namespace(cls, value: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9-]{1,63}", value):
            raise ValueError("SERVICE_NAMESPACE must be a valid product namespace")
        return value

    @field_validator("environment")
    @classmethod
    def _environment(cls, value: str) -> str:
        if value not in {"development", "staging", "production"}:
            raise ValueError("DEPLOYMENT_ENVIRONMENT must be a known release environment")
        return value

    @field_validator("endpoint")
    @classmethod
    def _collector_origin(cls, value: str) -> str:
        if not value:
            return ""
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"https", "http"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or len(value) > 2048
            or parsed.path.endswith(("/v1/logs", "/v1/traces", "/v1/metrics"))
        ):
            raise ValueError("OTLP_ENDPOINT must be one valid collector base URL")
        return value.rstrip("/")

    @model_validator(mode="after")
    def _collector_security(self) -> ObservabilitySettings:
        # Shared collector credentials must never travel over plaintext
        # non-loopback HTTP, nor become an inert App-specific secret.
        bearer = self.bearer_token
        if bearer is not None and bearer.get_secret_value():
            if not self.endpoint:
                raise ValueError("OTLP_BEARER_TOKEN requires OTLP_ENDPOINT")
            parsed = urlsplit(self.endpoint)
            if parsed.scheme != "https" and parsed.hostname not in {
                "localhost",
                "127.0.0.1",
                "::1",
            }:
                raise ValueError("OTLP_BEARER_TOKEN requires TLS collector transport")
        if self.endpoint:
            if not self.service_name:
                raise ValueError("OTEL_SERVICE_NAME required for active OTLP")
            if self.service_version == "unknown":
                raise ValueError("active Briareus OTLP requires known installed release version")
        return self

    @property
    def enabled(self) -> bool:
        return bool(self.endpoint)

    @property
    def resolved_instance_id(self) -> str:
        return gethostname()

    @property
    def service_version(self) -> str:
        """Immutable source distribution version, not release mutable ENV."""
        try:
            return distribution_version("briareus")
        except PackageNotFoundError:
            return "unknown"

    def signal_endpoint(self, signal: str) -> str:
        if signal not in {"logs", "traces", "metrics"}:
            raise ValueError("unsupported OTLP signal")
        return f"{self.endpoint}/v1/{signal}" if self.endpoint else ""

    @property
    def timeout_seconds(self) -> float:
        return self.timeout_ms / 1000


class AdminApiClientSettings(ProcessSettings):
    url: str = Field("http://admin-api:8000", validation_alias="ADMIN_API_URL")
    service_token: str = Field("", validation_alias="ADMIN_API_SERVICE_TOKEN")
    timeout_seconds: float = Field(
        10,
        gt=0,
        le=60,
        validation_alias="ADMIN_API_TIMEOUT_SECONDS",
    )

    _strip_values = field_validator("url", "service_token", mode="before")(
        staticmethod(_strip_string)
    )
