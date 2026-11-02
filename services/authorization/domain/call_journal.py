"""A signed past MCP effect is evidence, never renewed execution authority."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CallEvidence:
    request_uuid: UUID
    actor_uuid: UUID
    project_uuid: UUID
    agent_session_uuid: UUID | None
    node_uuid: UUID
    placement_uuid: UUID
    module: str
    method: str
    tool: str | None
    issued_at: int
    expires_at: int

    @property
    def entity_uuid(self) -> UUID:
        return (
            self.agent_session_uuid if self.agent_session_uuid is not None else self.placement_uuid
        )

    def require_recent_call(self, now: float) -> None:
        if (
            self.method != "tools/call"
            or not self.tool
            or not 0 < self.expires_at - self.issued_at <= 5
            or not now - 86400 < self.issued_at <= now + 2
        ):
            raise ValueError("Recent actual tool call required")


@dataclass(frozen=True, slots=True)
class CallJournalEntry:
    evidence: CallEvidence
    status: str
    duration_ms: int

    @property
    def event_name(self) -> str:
        return "mcp.call." + self.status

    def require_valid(self) -> None:
        if self.status not in {"completed", "failed", "unknown"}:
            raise ValueError("Unsupported MCP outcome")
        if not 0 <= self.duration_ms <= 86400000:
            raise ValueError("Invalid MCP call duration")
