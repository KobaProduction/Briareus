"""Read-only Platform agent directory; identities remain owned by Platform."""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from .directory_queries import DirectoryPageSelection


@dataclass(frozen=True, slots=True)
class AgentQuery:
    project: UUID
    id: UUID | None = None
    page: DirectoryPageSelection = field(default_factory=DirectoryPageSelection)

    @property
    def method(self) -> str:
        return "agents.list" if self.id is None else "agents.get"


@dataclass(frozen=True, slots=True)
class AgentItem:
    id: UUID
    project_uuid: UUID
    parent_agent_id: UUID | None
    name: str
    enabled: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AgentDetail:
    item: AgentItem


@dataclass(frozen=True, slots=True)
class AgentPage:
    items: tuple[AgentItem, ...]
    has_more: bool
    next_cursor: str | None


AgentDirectory = AgentDetail | AgentPage


@dataclass(frozen=True, slots=True)
class AgentReceipt:
    status: int
    directory: AgentDirectory | None = None
