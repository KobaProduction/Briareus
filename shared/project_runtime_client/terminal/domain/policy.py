"""Workspace names and bounded job controls independent of the process driver."""

import math
import re
from dataclasses import dataclass


class TerminalError(RuntimeError):
    """Base terminal/workspace error."""


@dataclass(frozen=True, slots=True)
class WorkspaceIdentity:
    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", normalized):
            raise TerminalError(
                "workspace_id must start with an alphanumeric character and contain only "
                "letters, digits, dot, underscore or hyphen"
            )
        object.__setattr__(self, "value", normalized)


@dataclass(frozen=True, slots=True)
class EnvironmentVariable:
    name: str
    value: str

    def __post_init__(self) -> None:
        if "\x00" in self.name or "=" in self.name or not self.name:
            raise TerminalError(f"invalid environment variable name: {self.name!r}")
        if "\x00" in self.value:
            raise TerminalError(f"invalid environment value for {self.name}")


@dataclass(frozen=True, slots=True)
class TerminalSize:
    cols: int
    rows: int

    def __post_init__(self) -> None:
        if not 1 <= self.cols <= 1000 or not 1 <= self.rows <= 1000:
            raise TerminalError("terminal size must be between 1 and 1000")


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    older_than_hours: int
    limit: int

    def __post_init__(self) -> None:
        if not 1 <= self.older_than_hours <= 24 * 3650:
            raise TerminalError("older_than_hours must be between 1 and 87600")
        if not 1 <= self.limit <= 10000:
            raise TerminalError("limit must be between 1 and 10000")


@dataclass(frozen=True, slots=True)
class JobPage:
    offset: int
    limit: int

    def __post_init__(self) -> None:
        if self.offset < 0:
            raise TerminalError("offset must be >= 0")
        if not 1 <= self.limit <= 1000:
            raise TerminalError("limit must be between 1 and 1000")


@dataclass(frozen=True, slots=True)
class PositiveTimeout:
    seconds: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.seconds) or self.seconds <= 0:
            raise TerminalError("timeout_seconds must be finite and positive")


@dataclass(frozen=True, slots=True)
class JobRuntimeLimit:
    requested: float | None
    runtime: float | None

    def __post_init__(self) -> None:
        if self.requested is not None:
            PositiveTimeout(self.requested)

    @property
    def seconds(self) -> float | None:
        limits = tuple(value for value in (self.requested, self.runtime) if value is not None)
        return min(limits) if limits else None
