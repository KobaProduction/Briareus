"""Existing private resource inspection response shapes."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class TerminalInspection:
    project_uuid: UUID
    resource_id: str
    resource_revision: int
    tools: list[str]
    isolated: bool = True


@dataclass(frozen=True)
class InspectionDenied:
    error: str = "AUTHORIZATION_OWNER_REQUIRED"


@dataclass(frozen=True, slots=True)
class ControllerLive:
    state: str = "live"
    mode: str = "private-owner-runtime"
