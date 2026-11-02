"""Passive browser facts; these selectors confer no execution authority."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class BrowserObservationTarget:
    project_uuid: UUID
    placement_uuid: UUID
    fingerprint: str
    actor_uuid: UUID
    agent_session_uuid: UUID
    grant_revision: int


@dataclass(frozen=True, slots=True)
class BrowserObservedFrame:
    source_request_uuid: UUID
    captured_at: float
    page_id: str
    url: str
    title: str
    png_base64: str


@dataclass(frozen=True, slots=True)
class NodeBrowserObservation:
    target: BrowserObservationTarget
    frame: BrowserObservedFrame | None
