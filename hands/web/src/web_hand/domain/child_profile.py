"""A private command may bind only a supervisor-selected session profile."""

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ChildProfile:
    value: str

    def require_selected(self) -> None:
        if re.fullmatch(r"/browser/session-[a-f0-9]{64}", self.value) is None:
            raise ValueError("Supervisor-selected session profile required")
