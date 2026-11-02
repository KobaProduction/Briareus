"""Fresh effects and catalogue requirements of an isolated Serena session."""

import math
from dataclasses import dataclass
from uuid import UUID

REQUIRED_TOOLS = frozenset(
    {
        "initial_instructions",
        "activate_project",
        "find_symbol",
        "get_symbols_overview",
        "find_referencing_symbols",
        "replace_symbol_body",
        "rename_symbol",
        "execute_shell_command",
    }
)


@dataclass(frozen=True)
class EffectAuthority:
    request_uuid: UUID
    tool: str
    expires_at: float
    background: bool = False

    def require_current(self, now: float, tools: frozenset[str]) -> None:
        if (
            self.request_uuid.version != 4
            or self.tool not in tools
            or not math.isfinite(self.expires_at)
            or not 0 < self.expires_at - now <= 5
        ):
            raise ValueError("Current exact Serena effect required")

    def require_outcome_current(self, now: float) -> None:
        if not self.background and self.expires_at <= now:
            raise ValueError("Serena outcome expired")


@dataclass(frozen=True)
class IsolationFacts:
    uid: int
    gid: int
    no_new_privileges: bool
    effective_capabilities: int
    readonly_root: bool
    network_interfaces: frozenset[str]

    def require_isolated(self) -> None:
        if (
            self.uid != 1000
            or self.gid != 1000
            or not self.no_new_privileges
            or self.effective_capabilities != 0
            or not self.readonly_root
            or self.network_interfaces != frozenset({"lo"})
        ):
            raise ValueError("Offline unprivileged readonly-root Serena runtime required")


def require_catalogue(version: str, expected_version: str, tools: frozenset[str]) -> None:
    if version != expected_version:
        raise ValueError("Actual pinned Serena server metadata required")
    if not tools >= REQUIRED_TOOLS:
        raise ValueError("Actual complete Serena LSP tools required")
