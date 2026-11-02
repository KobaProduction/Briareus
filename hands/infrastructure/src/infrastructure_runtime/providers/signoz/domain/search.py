"""A bounded telemetry search is independent of the provider query language."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class TelemetrySearch:
    signal: Literal["logs", "traces"]
    start_ms: int
    end_ms: int
    expression: str
    limit: int
    offset: int

    def __post_init__(self) -> None:
        if self.signal not in {"logs", "traces"}:
            raise ValueError("Logs or traces search required")
        if self.start_ms <= 0 or self.end_ms <= self.start_ms:
            raise ValueError("start_ms and end_ms must define a positive time range")
        if not 1 <= self.limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        if self.offset < 0:
            raise ValueError("offset must be >= 0")
