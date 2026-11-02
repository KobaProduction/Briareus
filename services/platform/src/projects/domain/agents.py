"""Project-scoped AgentIdentity directory facts."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class AgentItem:
    id: UUID
    project_uuid: UUID
    parent_agent_id: UUID | None
    name: str
    enabled: bool
    created_at: str


@dataclass(frozen=True, slots=True)
class AgentDetail:
    item: AgentItem


@dataclass(frozen=True, slots=True)
class AgentPage:
    items: tuple[AgentItem, ...]
    has_more: bool
    next_cursor: UUID | None
