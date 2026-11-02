from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence

from application.frontend_telemetry import FrontendTelemetryEvent
from application.telemetry_receipt import TelemetryEnqueueReceipt
from domain.frontend_telemetry import FrontendLogEvent
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

from common.audit_payloads import redact_json
from common.observability import otlp_headers, telemetry_resource
from common.settings import ObservabilitySettings

_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warn": logging.WARNING,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}


def _emit_event(logger: logging.Logger, event: FrontendLogEvent) -> None:
    attributes: dict[str, str | int | float | bool] = {
        target: value
        for value, target in (
            (event.id, "frontend.event.id"),
            (event.name, "frontend.event.name"),
            (event.occurred_at, "frontend.occurred_at"),
            (event.route, "frontend.route"),
            (event.duration_ms, "frontend.duration_ms"),
        )
        if value is not None
    }
    for attribute in event.attributes:
        normalized = attribute.key.strip().replace(" ", "_")
        if normalized:
            attributes[f"frontend.attribute.{normalized}"] = attribute.value
    name = event.name or "frontend.event"
    level = _LEVELS.get((event.level or "info").casefold(), logging.INFO)
    logger.log(level, name, extra=attributes)


class FrontendTelemetryProxy:
    """Emit authenticated browser diagnostics through the shared OTLP transport."""

    def __init__(
        self,
        settings: ObservabilitySettings,
        *,
        service_name: str = "admin-ui",
    ) -> None:
        self.settings = settings
        self.service_name = service_name
        self._provider: LoggerProvider | None = None
        self._logger: logging.Logger | None = None

        if not settings.enabled:
            return

        authorization = otlp_headers(settings)
        provider = LoggerProvider(
            resource=telemetry_resource(
                settings,
                "frontend",
                service_name=service_name,
            )
        )
        provider.add_log_record_processor(
            BatchLogRecordProcessor(
                OTLPLogExporter(
                    endpoint=settings.signal_endpoint("logs"),
                    headers={"Authorization": authorization.authorization}
                    if authorization
                    else None,
                    timeout=settings.timeout_seconds,
                )
            )
        )
        handler = LoggingHandler(level=logging.DEBUG, logger_provider=provider)
        logger = logging.Logger("briareus.frontend_telemetry", level=logging.INFO)
        logger.propagate = False
        logger.addHandler(handler)
        self._provider = provider
        self._logger = logger

    @property
    def enabled(self) -> bool:
        return self._provider is not None and self._logger is not None

    def start(self) -> None:
        """Kept for lifecycle symmetry; OTLP batching starts with the provider."""

    async def close(self) -> None:
        provider = self._provider
        self._provider = None
        self._logger = None
        if provider is None:
            return
        await asyncio.to_thread(provider.force_flush, timeout_millis=self.settings.timeout_ms)
        await asyncio.to_thread(provider.shutdown)

    def enqueue(self, events: Sequence[FrontendLogEvent]) -> TelemetryEnqueueReceipt:
        logger = self._logger
        if logger is None:
            return TelemetryEnqueueReceipt(
                accepted=0, queued_batches=0, dropped_batches=len(events)
            )

        accepted = 0
        for raw_event in events:
            try:
                wire = FrontendTelemetryEvent.from_record(raw_event)
                redacted = redact_json(
                    wire.model_dump(mode="json", by_alias=True, exclude_none=True)
                )
                event = FrontendTelemetryEvent.model_validate_json(redacted).domain()
            except ValueError:
                continue
            _emit_event(logger, event)
            accepted += 1

        return TelemetryEnqueueReceipt(
            accepted=accepted, queued_batches=0, dropped_batches=len(events) - accepted
        )
