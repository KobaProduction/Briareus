"""Ports consumed by telemetry batching infrastructure."""

from typing import Protocol

from .events import InvocationEvent


class TelemetryAuditClient(Protocol):
    def record_invocations(self, events: list[InvocationEvent]) -> None: ...
