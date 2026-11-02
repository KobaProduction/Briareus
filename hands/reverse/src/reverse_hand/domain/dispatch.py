"""Engine selection and catalogue membership, independent of SDK argument documents."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

Engine = Literal["ghidra", "radare2"]


@dataclass(frozen=True, slots=True)
class EngineCatalogue:
    engine: Engine
    names: frozenset[str]


@dataclass(frozen=True, slots=True)
class EngineCommand:
    engine: Engine
    tool: str | None

    def require_available(self, catalogue: EngineCatalogue) -> None:
        if self.engine != catalogue.engine:
            raise ValueError("Exact analysis engine catalogue required")
        if self.tool is not None and self.tool not in catalogue.names:
            raise ValueError("Exact actual engine tool required")


@dataclass(frozen=True, slots=True)
class AnalysisRequest:
    request_uuid: UUID
    command: EngineCommand
    expires_at: int
    long_operation: bool = False
