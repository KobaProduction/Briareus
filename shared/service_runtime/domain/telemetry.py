"""Bounded service identity used by telemetry infrastructure adapters."""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class TelemetryAuthorization:
    authorization: str = field(repr=False)


@dataclass(frozen=True)
class TelemetryIdentity:
    service_name: str
    namespace: str
    version: str
    instance_id: str
    environment: str
    scope: str

    def __post_init__(self) -> None:
        if not self.service_name:
            raise ValueError("OTEL_SERVICE_NAME required for enabled Briareus telemetry")
