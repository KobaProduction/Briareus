from __future__ import annotations

from typing import Literal, Protocol

from briareus_json_values import JsonValue, StrictModel
from pydantic import BaseModel, Field

from control_panel_api.domain.accounts import Provider

type RealtimeTopic = Literal[
    "mcp.calls", "system.metrics", "system.notifications", "browser.runtime", "management.events"
]
type EventData = BaseModel | JsonValue


class EventPublisher(Protocol):
    def __call__(self, topic: str, event_type: str, data: EventData) -> object: ...


class AccountReference(StrictModel):
    id: str
    provider: Provider


class AccountVerificationEvent(AccountReference):
    ok: bool


class RetentionApplied(StrictModel):
    removed: int = Field(ge=0)


class MetricsHeartbeat(StrictModel):
    monotonic_seconds: float
    status: Literal["ok"] = "ok"
