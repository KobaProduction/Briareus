from __future__ import annotations

from typing import Literal

from briareus_json_values import StrictModel
from pydantic import Field

type TelemetryAttribute = str | int | float | bool | None


class FrontendTelemetryEvent(StrictModel):
    id: str
    name: str
    level: Literal["debug", "info", "warn", "error"]
    occurredAt: str
    durationMs: float | None = None
    route: str
    attributes: dict[str, TelemetryAttribute] = Field(default_factory=dict)


class FrontendTelemetryEnvelope(StrictModel):
    version: Literal[1] = 1
    events: list[FrontendTelemetryEvent]


class FrontendTelemetryAcceptance(StrictModel):
    accepted: int
    queued_batches: int
    dropped_batches: int
