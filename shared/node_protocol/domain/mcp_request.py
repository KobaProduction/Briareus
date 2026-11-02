"""Facts needed for authorization; executable MCP arguments stay at the wire boundary."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class McpRequestFacts:
    method: str
    tool: str | None
    arguments_digest: str
    original_tool: str | None = None
