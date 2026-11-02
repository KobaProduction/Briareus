"""Realtime Panel protocol vocabulary and authority continuity rules."""

from dataclasses import dataclass

from .platform_authority import PanelOidcSession, ResolvedPlatformUser

REALTIME_TOPICS = frozenset(
    {
        "mcp.calls",
        "system.metrics",
        "system.notifications",
        "browser.runtime",
        "management.events",
        "platform.context",
        "access.sessions",
    }
)
MODULE_METHODS = frozenset(
    {
        "browser.resources",
        "browser.command",
        "terminal.resources",
        "terminal.command",
        "files.resources",
        "files.command",
        "analysis.resources",
        "analysis.command",
    }
)
PLATFORM_METHODS = frozenset(
    {"platform.inventory", "platform.command", "platform.team", "platform.directory"}
)


@dataclass(frozen=True, slots=True)
class PanelContext:
    session: PanelOidcSession
    proof: ResolvedPlatformUser


def same_authority(current: PanelContext, original: PanelContext) -> bool:
    return (
        current.proof.user_uuid == original.proof.user_uuid
        and current.proof.role == original.proof.role
        and {item.project_uuid for item in current.proof.projects}
        == {item.project_uuid for item in original.proof.projects}
    )


@dataclass(frozen=True, slots=True)
class RpcFault:
    message: str
    code: int = -32000
    uncertain: bool | None = None


@dataclass(frozen=True, slots=True)
class TopicSelection:
    topics: tuple[str, ...]
    cursor: str | None


@dataclass(frozen=True, slots=True)
class HistorySelection:
    topics: tuple[str, ...]
    before: str | None
    limit: int
    project: str | None
