"""Explicit frontend log transport fields and their framework-free observations."""

from datetime import datetime
from typing import Literal, Self

from domain.frontend_telemetry import FrontendLogAttribute, FrontendLogEvent
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr


class FrontendTelemetryEvent(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: StrictStr | None = None
    name: StrictStr | None = None
    level: StrictStr | None = None
    occurred_at: StrictStr | None = Field(default=None, alias="occurredAt")
    route: StrictStr | None = None
    duration_ms: StrictInt | StrictFloat | None = Field(default=None, alias="durationMs")
    # OTLP attributes are a keyed scalar collection, never an arbitrary JSON document.
    attributes: dict[str, StrictStr | StrictInt | StrictFloat | StrictBool | None] = Field(
        default_factory=dict
    )

    def domain(self) -> FrontendLogEvent:
        return FrontendLogEvent(
            id=self.id,
            name=self.name,
            level=self.level,
            occurred_at=self.occurred_at,
            route=self.route,
            duration_ms=self.duration_ms,
            attributes=tuple(
                FrontendLogAttribute(key, "" if value is None else value)
                for key, value in self.attributes.items()
            ),
        )

    @classmethod
    def from_record(cls, event: FrontendLogEvent) -> Self:
        return cls(
            id=event.id,
            name=event.name,
            level=event.level,
            occurred_at=event.occurred_at,
            route=event.route,
            duration_ms=event.duration_ms,
            attributes={attribute.key: attribute.value for attribute in event.attributes},
        )


class FrontendTelemetryBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    events: list[FrontendTelemetryEvent] = Field(min_length=1, max_length=500)


class SafeBrowserTelemetryEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    kind: Literal["navigation", "http_failure", "render_error", "performance", "interaction"]
    component: Literal[
        "auth",
        "navigation",
        "project",
        "team",
        "users",
        "agents",
        "sessions",
        "resources",
        "settings",
    ]
    outcome: Literal["ok", "denied", "failed", "cancelled", "pending"]
    route_key: Literal[
        "login",
        "projects",
        "teams",
        "users",
        "agents",
        "sessions",
        "resources",
        "settings",
        "unknown",
    ]
    occurred_at: datetime
    duration_ms: int = Field(default=0, ge=0, le=300_000)
