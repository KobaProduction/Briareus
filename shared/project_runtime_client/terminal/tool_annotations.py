"""Terminal metadata selection with an owner-local nominal result constructor."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from mcp.types import ToolAnnotations


@dataclass(frozen=True, slots=True)
class _TerminalAnnotations[LabelsT]:
    factory: Callable[
        [
            ToolAnnotations | None,
            ToolAnnotations | None,
            ToolAnnotations | None,
            ToolAnnotations | None,
        ],
        LabelsT,
    ]

    def __call__(self, include_metadata: bool) -> LabelsT:
        if not include_metadata:
            return self.factory(None, None, None, None)

        from service_runtime.runtime_annotations import (
            DESTRUCTIVE_EXTERNAL,
            DESTRUCTIVE_LOCAL,
            READ_ONLY_LOCAL,
            WRITE_LOCAL,
        )

        return self.factory(DESTRUCTIVE_EXTERNAL, DESTRUCTIVE_LOCAL, READ_ONLY_LOCAL, WRITE_LOCAL)
