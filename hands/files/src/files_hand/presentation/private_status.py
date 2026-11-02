"""Private owner listener response schemas."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class LiveStatus:
    state: Literal["live"] = "live"
    mode: Literal["private-owner-runtime"] = "private-owner-runtime"


@dataclass(frozen=True, slots=True)
class NotReadyStatus:
    state: Literal["not_ready"] = "not_ready"
    mcp: Literal["resource_activation_pending"] = "resource_activation_pending"


@dataclass(frozen=True, slots=True)
class FilesInspection:
    project_uuid: str
    isolated: bool
    resource_id: str
    resource_revision: int
    tools: tuple[str, ...]
