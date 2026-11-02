"""Supported topics and subscription commands for the retained event stream."""

from dataclasses import dataclass
from typing import Final, Literal

REALTIME_TOPICS: Final[frozenset[str]] = frozenset(
    {
        "mcp.calls",
        "system.metrics",
        "system.notifications",
        "browser.runtime",
        "admin.events",
        "access.sessions",
    }
)


@dataclass(frozen=True, slots=True)
class RealtimeCommand:
    kind: str
    topics: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MetricsHeartbeat:
    monotonic_seconds: float
    status: Literal["ok"] = "ok"


@dataclass(frozen=True, slots=True)
class BrowserDebugIssued:
    page_id: str
    target_id: str


@dataclass(frozen=True, slots=True)
class BrowserPolicyFailure:
    error: str


@dataclass(frozen=True, slots=True)
class BrowserUnavailable:
    error: str
    available: Literal[False] = False


@dataclass(frozen=True, slots=True)
class AccountIdentity:
    id: str
    provider: str


@dataclass(frozen=True, slots=True)
class AccountVerified(AccountIdentity):
    ok: bool


def validate_topic(topic: str) -> str:
    normalized = topic.strip()
    if normalized not in REALTIME_TOPICS:
        raise ValueError(f"unsupported realtime topic: {normalized}")
    return normalized
