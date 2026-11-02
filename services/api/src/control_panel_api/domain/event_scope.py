"""Realtime visibility bindings; an absent scope never grants delivery."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

type ScopeKind = Literal[
    "", "broadcast", "operator", "actor", "project", "project_operator", "access"
]


@dataclass(frozen=True, slots=True)
class EventScope:
    kind: ScopeKind
    id: UUID | None = None
    project: UUID | None = None
    actor: UUID | None = None

    def __post_init__(self) -> None:
        if self.kind in {"actor", "project", "project_operator"}:
            valid = isinstance(self.id, UUID) and self.project is None and self.actor is None
        elif self.kind == "access":
            valid = self.id is None and isinstance(self.project, UUID)
            valid = valid and (self.actor is None or isinstance(self.actor, UUID))
        else:
            valid = self.kind in {"", "broadcast", "operator"}
            valid = valid and self.id is None and self.project is None and self.actor is None
        if not valid:
            raise ValueError("Invalid realtime visibility binding")
