from __future__ import annotations

import asyncio
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass

from briareus_telemetry.audit_payloads import redact_payload

from control_panel_api.domain.frontend_telemetry import (
    FrontendTelemetryAcceptance,
    FrontendTelemetryEnvelope,
    FrontendTelemetryEvent,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TelemetryUpstream:
    url: str
    bearer_token: str = ""
    timeout_seconds: float = 5.0


class FrontendTelemetryProxy:
    """Bounded, failure-isolated telemetry batch forwarder."""

    def __init__(self, upstream: TelemetryUpstream, *, max_batches: int = 128) -> None:
        self.upstream = upstream
        self.queue: asyncio.Queue[list[FrontendTelemetryEvent]] = asyncio.Queue(maxsize=max_batches)
        self._worker: asyncio.Task[None] | None = None
        self.dropped_batches = 0

    def start(self) -> None:
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._run(), name="frontend-telemetry-forwarder")

    async def close(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
            self._worker = None

    def enqueue(self, events: list[FrontendTelemetryEvent]) -> FrontendTelemetryAcceptance:
        sanitized = [
            FrontendTelemetryEvent.model_validate(
                redact_payload(event.model_dump(mode="json", exclude_unset=True))
            ) for event in events
        ]
        if self.queue.full():
            try:
                self.queue.get_nowait()
                self.queue.task_done()
                self.dropped_batches += 1
            except asyncio.QueueEmpty:
                pass
        self.queue.put_nowait(sanitized)
        return FrontendTelemetryAcceptance(
            accepted=len(sanitized),
            queued_batches=self.queue.qsize(),
            dropped_batches=self.dropped_batches,
        )

    def _send(self, events: list[FrontendTelemetryEvent]) -> None:
        if not self.upstream.url:
            return
        body = FrontendTelemetryEnvelope(version=1, events=events).model_dump_json(
            exclude_unset=True
        ).encode()
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.upstream.bearer_token:
            headers["Authorization"] = f"Bearer {self.upstream.bearer_token}"
        request = urllib.request.Request(
            self.upstream.url,
            data=body,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.upstream.timeout_seconds) as response:
            response.read(1024)

    async def _run(self) -> None:
        backoff = 0.5
        while True:
            batch = await self.queue.get()
            try:
                combined = list(batch)
                while len(combined) < 1000 and not self.queue.empty():
                    next_batch = self.queue.get_nowait()
                    combined.extend(next_batch)
                    self.queue.task_done()
                try:
                    await asyncio.to_thread(self._send, combined)
                    backoff = 0.5
                except (OSError, urllib.error.URLError, TimeoutError):
                    logger.warning("frontend telemetry upstream unavailable; batch dropped")
                    await asyncio.sleep(backoff)
                    backoff = min(10.0, backoff * 2)
            finally:
                self.queue.task_done()
