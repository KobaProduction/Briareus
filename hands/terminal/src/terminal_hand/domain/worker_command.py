"""The private child executes only tools in its prepared catalogue."""

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkerToolPolicy:
    tools: frozenset[str]

    def require_available(self, tool: str) -> None:
        if tool not in self.tools:
            raise ValueError("Invalid supervisor command")
