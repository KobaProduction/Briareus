"""Pure watch-path safety and change-to-consumer decisions."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from fnmatch import fnmatchcase


class ImpactError(RuntimeError):
    pass


@dataclass(frozen=True)
class WatchPattern:
    value: str

    def __post_init__(self) -> None:
        if not self.value or self.value.startswith(("/", "!")):
            raise ImpactError("unsafe watch path")
        if ".." in self.value.split("/"):
            raise ImpactError("unsafe watch path")

    def matches(self, name: str) -> bool:
        if self.value.endswith("/**"):
            prefix = self.value[:-3].rstrip("/")
            return name.startswith(prefix + "/")
        return fnmatchcase(name, self.value)


@dataclass(frozen=True)
class WatchPlan:
    module: str
    patterns: tuple[WatchPattern, ...]

    def __post_init__(self) -> None:
        if not self.patterns:
            raise ImpactError(f"{self.module}: no watch paths")
        values = [pattern.value for pattern in self.patterns]
        if len(values) != len(set(values)):
            raise ImpactError(f"{self.module}: duplicate watch path")

    def covers(self, name: str) -> bool:
        return any(pattern.matches(name) for pattern in self.patterns)


@dataclass(frozen=True)
class FileImpact:
    path: str
    modules: tuple[str, ...]


@dataclass(frozen=True)
class ImpactReport:
    files: tuple[FileImpact, ...]

    def consumers(self, path: str) -> tuple[str, ...]:
        for entry in self.files:
            if entry.path == path:
                return entry.modules
        raise KeyError(path)


def calculate_impact(plans: Sequence[WatchPlan], changed: Sequence[str]) -> ImpactReport:
    # JSON output historically has one property per path, in first-seen order.
    names = dict.fromkeys(changed)
    return ImpactReport(
        tuple(
            FileImpact(name, tuple(plan.module for plan in plans if plan.covers(name)))
            for name in names
        )
    )
