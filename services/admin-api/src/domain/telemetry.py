"""Invocation values and pagination rules without transport or persistence dependencies."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from .validation import require_boolean, require_datetime, require_integer, require_text


def require_invocation_status(value: object, *, optional: bool = False) -> None:
    if optional and value is None:
        return
    if not isinstance(value, str) or value not in {"success", "error"}:
        raise ValueError("Invocation status must be success or error")


def invocation_duration(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not value >= 0:
        raise ValueError("Invocation duration must be a nonnegative number")
    return float(value)


@dataclass(frozen=True, slots=True, kw_only=True)
class InvocationObservation:
    """Call facts shared by validated records and redacted audit observations."""

    id: str = field(default_factory=lambda: str(uuid4()))
    request_id: str = ""
    module: str
    tool: str
    account_id: str = ""
    provider: str = ""
    status: Literal["success", "error"]
    duration_ms: float
    error_type: str = ""
    arguments_json: str = ""
    result_json: str = ""
    error_message: str = ""
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True, kw_only=True)
class Invocation(InvocationObservation):
    def __post_init__(self) -> None:
        require_text(self.id, name="id")
        if re.fullmatch(r"[0-9a-f-]{36}", self.id) is None:
            raise ValueError("Invocation identifier must have 36 lowercase hex/hyphen characters")
        require_text(self.module, name="module", minimum=1, maximum=64)
        require_text(self.tool, name="tool", minimum=1, maximum=256)
        require_invocation_status(self.status)
        require_datetime(self.occurred_at, name="occurred_at")
        object.__setattr__(self, "duration_ms", invocation_duration(self.duration_ms))
        for name, value in (
            ("request_id", self.request_id),
            ("account_id", self.account_id),
            ("provider", self.provider),
            ("error_type", self.error_type),
            ("arguments_json", self.arguments_json),
            ("result_json", self.result_json),
            ("error_message", self.error_message),
        ):
            require_text(value, name=name)

    def captured(self, include_payloads: bool) -> Invocation:
        if include_payloads:
            return self
        return replace(self, arguments_json="", result_json="", error_message="")


@dataclass(frozen=True, slots=True)
class InvocationBatch:
    events: tuple[InvocationObservation, ...]
    count: int

    def __post_init__(self) -> None:
        require_integer(self.count, name="count")
        if self.count != len(self.events):
            raise ValueError("Invocation batch count must match its events")


@dataclass(frozen=True, slots=True, kw_only=True)
class InvocationQuery:
    limit: int = 100
    offset: int = 0
    cursor_at: datetime | None = None
    cursor_id: str = ""
    module: str = ""
    tool: str = ""
    provider: str = ""
    account_id: str = ""
    status: Literal["success", "error"] | None = None
    search: str = ""

    def __post_init__(self) -> None:
        require_integer(self.limit, name="limit", minimum=1, maximum=500)
        require_integer(self.offset, name="offset")
        if self.cursor_at is not None:
            require_datetime(self.cursor_at, name="cursor_at")
        require_text(self.cursor_id, name="cursor_id")
        require_invocation_status(self.status, optional=True)
        for name, value, maximum in (
            ("module", self.module, 64),
            ("tool", self.tool, 256),
            ("provider", self.provider, 32),
            ("account_id", self.account_id, 128),
            ("search", self.search, 256),
        ):
            require_text(value, name=name, maximum=maximum)


@dataclass(frozen=True, slots=True, kw_only=True)
class InvocationPage:
    events: list[Invocation]
    total: int
    count: int
    has_more: bool
    next_cursor_at: datetime | None = None
    next_cursor_id: str = ""

    def __post_init__(self) -> None:
        require_integer(self.total, name="total")
        require_integer(self.count, name="count")
        require_boolean(self.has_more, name="has_more")
        if not isinstance(self.events, list):
            raise ValueError("Invocation page requires a list of invocation records")
        if any(not isinstance(item, Invocation) for item in self.events):
            raise ValueError("Invocation page requires a list of invocation records")
        if self.next_cursor_at is not None:
            require_datetime(self.next_cursor_at, name="next_cursor_at")
        require_text(self.next_cursor_id, name="next_cursor_id")


@dataclass(frozen=True, slots=True)
class InvocationSummary:
    total: int
    errors: int
    error_rate: float
    average_duration_ms: float
