from __future__ import annotations

from os import getenv

from briareus_environment_models import ProcessSettings
from pydantic import Field, field_validator


class ObservabilitySettings(ProcessSettings):
    service_name: str = Field("briareus", validation_alias="OTEL_SERVICE_NAME")
    service_version: str = Field("0.1.0", validation_alias="OTEL_SERVICE_VERSION")
    service_instance_id: str = Field("", validation_alias="OTEL_SERVICE_INSTANCE_ID")
    environment: str = Field(
        min_length=1, max_length=63, pattern=r"^[a-z0-9][a-z0-9._-]*$",
        validation_alias="DEPLOYMENT_ENVIRONMENT",
    )
    namespace: str = Field("", validation_alias="OTEL_NAMESPACE")
    endpoint: str = Field("", validation_alias="OTEL_ENDPOINT")
    bearer_token: str = Field("", validation_alias="OTEL_BEARER_TOKEN")
    resource_attributes: str = Field("", validation_alias="OTEL_RESOURCE_ATTRIBUTES")
    log_level: str = Field("INFO", validation_alias="OTEL_LOG_LEVEL")
    timeout_ms: int = Field(
        10_000,
        ge=100,
        le=120_000,
        validation_alias="OTEL_EXPORTER_OTLP_TIMEOUT",
    )
    metric_export_interval_ms: int = Field(
        30_000,
        ge=1_000,
        le=300_000,
        validation_alias="OTEL_METRIC_EXPORT_INTERVAL",
    )

    @field_validator(
        "service_name",
        "service_version",
        "service_instance_id",
        "environment",
        "namespace",
        "endpoint",
        "bearer_token",
        "resource_attributes",
        "log_level",
        mode="before",
    )
    @classmethod
    def _strip_observability_strings(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @property
    def enabled(self) -> bool:
        return bool(self.endpoint)

    @property
    def resolved_instance_id(self) -> str:
        return self.service_instance_id or getenv("HOSTNAME") or "unknown"

    def signal_endpoint(self, signal: str) -> str:
        if signal not in {"logs", "traces", "metrics"}:
            raise ValueError(f"unsupported OTLP signal: {signal}")
        if not self.endpoint:
            return ""
        endpoint = self.endpoint.rstrip("/")
        for suffix in ("/v1/logs", "/v1/traces", "/v1/metrics"):
            if endpoint.endswith(suffix):
                endpoint = endpoint[: -len(suffix)]
                break
        return f"{endpoint}/v1/{signal}"

    @property
    def timeout_seconds(self) -> float:
        return self.timeout_ms / 1000
