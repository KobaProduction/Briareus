"""Frontend log observations; collector fields never represent access authority."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FrontendLogAttribute:
    key: str
    value: str | int | float | bool


@dataclass(frozen=True, slots=True, kw_only=True)
class FrontendLogEvent:
    id: str | None = None
    name: str | None = None
    level: str | None = None
    occurred_at: str | None = None
    route: str | None = None
    duration_ms: int | float | None = None
    attributes: tuple[FrontendLogAttribute, ...] = ()
