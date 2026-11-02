"""Immutable execution facts after transport validation and signature verification."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from .browser_observation import NodeBrowserObservation


@dataclass(frozen=True, slots=True)
class FailureFacts:
    stage: str
    component: str
    reason: str
    exit_code: int | None = None
    health_status: str | None = None
    oom_killed: bool | None = None
    health_exit_code: int | None = None


@dataclass(frozen=True, slots=True)
class ObservedLimits:
    memory_bytes: int
    cpu_millis: int
    pids: int


@dataclass(frozen=True, slots=True)
class ObservedModule:
    placement_uuid: UUID
    fingerprint: str
    running: bool
    ready: bool
    limits: ObservedLimits


@dataclass(frozen=True, slots=True)
class NodeConfiguration:
    node_uuid: UUID
    sequence: int
    enabled: bool


@dataclass(frozen=True, slots=True)
class NodeInventory:
    node_uuid: UUID
    enabled: bool
    event_cursor: int
    sequence: int
    items: tuple[ObservedModule, ...]


@dataclass(frozen=True, slots=True)
class NodeOperation:
    operation_uuid: UUID
    sequence: int
    phase: str
    error: str | None
    diagnostic: FailureFacts | None = None


@dataclass(frozen=True, slots=True)
class NodeFailure:
    code: str


type NodeReply = (
    NodeConfiguration | NodeInventory | NodeOperation | NodeFailure | NodeBrowserObservation
)


@dataclass(frozen=True, slots=True)
class NodeEvent:
    cursor: int
    node_uuid: UUID
    topic: Literal["operation", "configuration"]
    created_at: datetime
    payload: NodeOperation | NodeConfiguration
