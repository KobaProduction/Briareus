"""Bounded Core authority and stable stopped-process observations."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Literal

type LeaseIdentity = tuple[str, str, int] | tuple[Literal["human"], str, str, int]
type LeaseIdentityInput = tuple[str | int, ...] | list[str | int] | None
type LeaseExpiryInput = int | float | str | None


@dataclass(frozen=True, slots=True)
class ProcessAuthority:
    identity: LeaseIdentity
    expires_at: float

    @classmethod
    def parse(cls, identity: LeaseIdentityInput, expires_at: LeaseExpiryInput) -> ProcessAuthority:
        if not isinstance(identity, tuple) or not isinstance(expires_at, (int, float)):
            raise ValueError("Current bounded Core process authority is required")
        match identity:
            case ("human", str() as actor, str() as project, int() as resource_revision) if (
                type(resource_revision) is int
            ):
                return cls(("human", actor, project, resource_revision), expires_at)
            case (str() as actor, str() as session, int() as grant_revision) if (
                type(grant_revision) is int
            ):
                return cls((actor, session, grant_revision), expires_at)
        raise ValueError("Current bounded Core process authority is required")

    def require_current(self, now: float) -> None:
        if len(self.identity) == 4:
            _kind, actor, project, resource_revision = self.identity
            valid = bool(actor) and bool(project) and resource_revision >= 1
        else:
            actor, session, grant_revision = self.identity
            valid = bool(actor) and bool(session) and grant_revision >= 1
        if not valid or not 0 < self.expires_at - now <= 5:
            raise ValueError("Current bounded Core process authority is required")


@dataclass(frozen=True, slots=True)
class ProcessState:
    pid: int
    state: str


@dataclass(frozen=True, slots=True)
class ProcessInventory:
    processes: tuple[ProcessState, ...]

    def __iter__(self) -> Iterator[int]:
        return (process.pid for process in self.processes)

    def __bool__(self) -> bool:
        return bool(self.processes)

    def values(self) -> tuple[str, ...]:
        return tuple(process.state for process in self.processes)


def stopped_processes(states: Iterable[str]) -> bool:
    return all(state in {"T", "t"} for state in states)
